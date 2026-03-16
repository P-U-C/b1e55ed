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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


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


@router.post(
    "/producers/{producer_id}/activate",
    response_model=ActivateProducerResponse,
    summary="Activate a producer (onboarding → active)",
)
def activate_producer(
    producer_id: str,
    db: Database = Depends(get_db),
) -> ActivateProducerResponse:
    _ensure_tables(db)

    row = db.fetchone(
        "SELECT lifecycle_state FROM spi_producers WHERE producer_id = ?",
        (producer_id,),
    )
    if row is None:
        raise B1e55edError(
            code="spi.producer_not_found",
            message=f"Producer '{producer_id}' not found",
            status=404,
        )

    now = datetime.now(tz=UTC).isoformat()
    db.execute(
        "UPDATE spi_producers SET lifecycle_state = 'active', updated_at = ? WHERE producer_id = ?",
        (now, producer_id),
    )

    return ActivateProducerResponse(
        producer_id=producer_id,
        lifecycle_state="active",
    )
