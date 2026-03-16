"""SPI admin endpoints — producer registration and lifecycle management.

No auth for now: gated by network / reverse-proxy ACL in production.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.deps import get_db
from api.errors import B1e55edError
from api.routes.spi import _ensure_key_column
from engine.core.database import Database
from engine.spi.admission import _ensure_tables
from engine.spi.lifecycle import (
    check_promotion_criteria,
    get_producer,
    transition,
)
from engine.spi.slash import check_slash_conditions

router = APIRouter(prefix="/spi", tags=["spi-admin"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class RegisterProducerRequest(BaseModel):
    producer_id: str = Field(..., description='Unique producer slug e.g. "sendoeth"')
    producer_name: str = Field(..., description="Human-readable name")
    ingress_mode: str = Field("native", description='"native" or "adapter"')


class RegisterProducerResponse(BaseModel):
    producer_id: str
    api_key: str  # returned ONCE, not stored in plaintext


class ActivateProducerResponse(BaseModel):
    producer_id: str
    lifecycle_state: str


class ProducerStateResponse(BaseModel):
    producer_id: str
    producer_name: str
    lifecycle_state: str
    ingress_mode: str
    running_karma: float | None
    resolved_count: int
    promotion_eligibility: dict


class TransitionRequest(BaseModel):
    to_state: str = Field(..., description="Target lifecycle state")


class TransitionResponse(BaseModel):
    producer_id: str
    lifecycle_state: str
    previous_state: str


class SlashCheckResponse(BaseModel):
    producer_id: str
    triggered_conditions: list[dict]


class ProducerListItem(BaseModel):
    producer_id: str
    producer_name: str
    lifecycle_state: str
    ingress_mode: str
    registered_at: str | None


class ProducerListResponse(BaseModel):
    producers: list[ProducerListItem]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/producers",
    response_model=ProducerListResponse,
    summary="List all registered SPI producers",
)
def list_producers(
    db: Database = Depends(get_db),
) -> ProducerListResponse:
    _ensure_tables(db)

    rows = db.fetchall(
        """
        SELECT producer_id, producer_name, lifecycle_state, ingress_mode, registered_at
        FROM spi_producers
        ORDER BY registered_at ASC
        """
    )
    producers = [
        ProducerListItem(
            producer_id=str(r[0]),
            producer_name=str(r[1]),
            lifecycle_state=str(r[2]),
            ingress_mode=str(r[3]),
            registered_at=str(r[4]) if r[4] else None,
        )
        for r in rows
    ]
    return ProducerListResponse(producers=producers)


@router.post(
    "/producers",
    response_model=RegisterProducerResponse,
    status_code=201,
    summary="Register a new SPI producer",
    description=(
        "Creates a producer record with lifecycle_state='onboarding' and returns "
        "the plaintext API key once.  The key is stored as a sha256 hash — it "
        "cannot be recovered after this call."
    ),
)
def register_producer(
    body: RegisterProducerRequest,
    db: Database = Depends(get_db),
) -> RegisterProducerResponse:
    _ensure_key_column(db)

    # Collision check
    existing = db.fetchone(
        "SELECT producer_id FROM spi_producers WHERE producer_id = ?",
        (body.producer_id,),
    )
    if existing is not None:
        raise B1e55edError(
            code="spi.producer_exists",
            message=f"Producer '{body.producer_id}' is already registered",
            status=409,
        )

    # Generate key: prefix + 32 random hex bytes
    raw_key = "spi_key_" + secrets.token_hex(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    now = datetime.now(tz=UTC).isoformat()
    db.execute(
        """
        INSERT INTO spi_producers (
            producer_id, producer_name, lifecycle_state, ingress_mode,
            api_key_hash, registered_at, created_at, updated_at
        ) VALUES (?, ?, 'onboarding', ?, ?, ?, ?, ?)
        """,
        (
            body.producer_id,
            body.producer_name,
            body.ingress_mode,
            key_hash,
            now,
            now,
            now,
        ),
    )

    return RegisterProducerResponse(
        producer_id=body.producer_id,
        api_key=raw_key,
    )


@router.get(
    "/producers/{producer_id}",
    response_model=ProducerStateResponse,
    summary="Get producer state, karma, and promotion eligibility",
)
def get_producer_state(
    producer_id: str,
    db: Database = Depends(get_db),
) -> ProducerStateResponse:
    _ensure_tables(db)

    producer = get_producer(db, producer_id)
    if producer is None:
        raise B1e55edError(
            code="spi.producer_not_found",
            message=f"Producer '{producer_id}' not found",
            status=404,
        )

    # Fetch latest karma
    karma_row = db.fetchone(
        """
        SELECT running_karma, resolved_count FROM spi_karma
        WHERE producer_id = ?
        ORDER BY epoch DESC LIMIT 1
        """,
        (producer_id,),
    )
    running_karma = karma_row[0] if karma_row else None
    resolved_count = karma_row[1] if karma_row else 0

    promotion_eligibility = check_promotion_criteria(db, producer_id)

    return ProducerStateResponse(
        producer_id=producer["producer_id"],
        producer_name=producer["producer_name"],
        lifecycle_state=producer["lifecycle_state"],
        ingress_mode=producer["ingress_mode"],
        running_karma=running_karma,
        resolved_count=resolved_count,
        promotion_eligibility=promotion_eligibility,
    )


@router.post(
    "/producers/{producer_id}/transition",
    response_model=TransitionResponse,
    summary="Manually transition producer lifecycle state",
)
def transition_producer(
    producer_id: str,
    body: TransitionRequest,
    db: Database = Depends(get_db),
) -> TransitionResponse:
    _ensure_tables(db)

    producer = get_producer(db, producer_id)
    if producer is None:
        raise B1e55edError(
            code="spi.producer_not_found",
            message=f"Producer '{producer_id}' not found",
            status=404,
        )

    previous_state = producer["lifecycle_state"]
    try:
        updated = transition(db, producer_id, body.to_state)
    except ValueError as exc:
        raise B1e55edError(
            code="spi.invalid_transition",
            message=str(exc),
            status=422,
        ) from exc

    return TransitionResponse(
        producer_id=producer_id,
        lifecycle_state=updated["lifecycle_state"],
        previous_state=previous_state,
    )


@router.get(
    "/producers/{producer_id}/slash-check",
    response_model=SlashCheckResponse,
    summary="Run slash condition check and return triggered conditions",
)
def slash_check(
    producer_id: str,
    db: Database = Depends(get_db),
) -> SlashCheckResponse:
    _ensure_tables(db)

    producer = get_producer(db, producer_id)
    if producer is None:
        raise B1e55edError(
            code="spi.producer_not_found",
            message=f"Producer '{producer_id}' not found",
            status=404,
        )

    triggered = check_slash_conditions(db, producer_id)

    return SlashCheckResponse(
        producer_id=producer_id,
        triggered_conditions=triggered,
    )


@router.post(
    "/producers/{producer_id}/activate",
    response_model=ActivateProducerResponse,
    summary="Activate a producer (uses lifecycle state machine)",
)
def activate_producer(
    producer_id: str,
    db: Database = Depends(get_db),
) -> ActivateProducerResponse:
    _ensure_tables(db)

    producer = get_producer(db, producer_id)
    if producer is None:
        raise B1e55edError(
            code="spi.producer_not_found",
            message=f"Producer '{producer_id}' not found",
            status=404,
        )

    try:
        updated = transition(db, producer_id, "active")
    except ValueError as exc:
        raise B1e55edError(
            code="spi.invalid_transition",
            message=str(exc),
            status=422,
        ) from exc

    return ActivateProducerResponse(
        producer_id=producer_id,
        lifecycle_state=updated["lifecycle_state"],
    )
