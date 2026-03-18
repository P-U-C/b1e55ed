"""SPI admin endpoints — producer registration and lifecycle management.

No auth for now: gated by network / reverse-proxy ACL in production.
"""

from __future__ import annotations

import hashlib
import secrets

try:
    from datetime import UTC, datetime
except ImportError:
    from datetime import datetime, timezone

    UTC = timezone.utc  # noqa: UP017

from fastapi import APIRouter, Body, Depends, HTTPException
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

FORGE_EXPECTED_CANDIDATES = 16**7
FORGE_RUST_RATE_PER_CORE = 5_000_000
FORGE_PYTHON_RATE = 50_000
FORGE_REQUIRED = False
FORGE_GRACE_PERIOD_DAYS = 90
FORGE_PREFIX = "0xb1e55ed"
FORGE_MESSAGE = "Every b1e55ed producer eventually needs a 0xb1e55ed vanity address. You can forge one now or later."


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class RegisterProducerRequest(BaseModel):
    producer_id: str = Field(..., description='Unique producer slug e.g. "sendoeth"')
    producer_name: str = Field(..., description="Human-readable name")
    ingress_mode: str = Field("native", description='"native" or "adapter"')


class ForgeOnboardingInfo(BaseModel):
    required: bool
    grace_period_days: int
    estimate_url: str
    message: str


class RegisterProducerResponse(BaseModel):
    producer_id: str
    api_key: str  # returned ONCE, not stored in plaintext
    forge: ForgeOnboardingInfo


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


class ForgeEstimateRequest(BaseModel):
    cpu_cores: int = Field(4, ge=1)
    cpu_model: str = ""
    has_rust: bool = False
    platform: str = ""


class ForgeEstimateResponse(BaseModel):
    estimated_seconds: int
    recommendation: str
    message: str
    instructions: dict[str, str]
    forge_required: bool
    grace_period_days: int


class ForgeCompleteRequest(BaseModel):
    forged_address: str
    signature: str


class ForgeCompleteResponse(BaseModel):
    producer_id: str
    forged_address: str
    verified: bool
    message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_forge_info(producer_id: str) -> ForgeOnboardingInfo:
    return ForgeOnboardingInfo(
        required=FORGE_REQUIRED,
        grace_period_days=FORGE_GRACE_PERIOD_DAYS,
        estimate_url=f"/api/v1/spi/producers/{producer_id}/forge-estimate",
        message=FORGE_MESSAGE,
    )


def _forge_binary_url(platform: str) -> str:
    platform_normalized = platform.lower()
    if platform_normalized.startswith("darwin"):
        return "https://github.com/P-U-C/b1e55ed/releases/latest/download/b1e55ed-forge-macos"
    if platform_normalized.startswith("linux"):
        return "https://github.com/P-U-C/b1e55ed/releases/latest/download/b1e55ed-forge-linux-x86_64"
    return "https://github.com/P-U-C/b1e55ed/releases/latest/download/b1e55ed-forge-linux-x86_64"


def _forge_recommendation(estimated_seconds: int) -> tuple[str, str]:
    if estimated_seconds < 60:
        return (
            "forge_now",
            f"Your machine can forge a 0xb1e55ed address in ~{estimated_seconds}s. We recommend forging now.",
        )

    if estimated_seconds < 600:
        return (
            "forge_background",
            f"Estimated forge time: ~{estimated_seconds // 60} minutes. You can forge in the background while submitting signals.",
        )

    return (
        "forge_later",
        (
            f"Estimated forge time: ~{estimated_seconds // 60} minutes. "
            "You can start submitting signals now and forge later. "
            "Your address will be mapped to your forged identity when ready."
        ),
    )


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
        forge=_build_forge_info(body.producer_id),
    )


@router.post(
    "/producers/{producer_id}/forge-estimate",
    response_model=ForgeEstimateResponse,
    summary="Estimate forge runtime and onboarding guidance",
)
def forge_estimate(
    producer_id: str,
    req: ForgeEstimateRequest = Body(...),
) -> ForgeEstimateResponse:
    # 7 hex chars = 16^7 = 268,435,456 expected candidates
    if req.has_rust:
        # Rust grinder: ~5M candidates/sec/core (conservative)
        rate = req.cpu_cores * FORGE_RUST_RATE_PER_CORE
    else:
        # Python fallback: ~50K/sec single-threaded
        rate = FORGE_PYTHON_RATE

    estimated_seconds = int(FORGE_EXPECTED_CANDIDATES / max(rate, 1))

    recommendation, message = _forge_recommendation(estimated_seconds)
    binary_url = _forge_binary_url(req.platform)

    instructions = {
        "download": f"curl -Lo b1e55ed-forge {binary_url} && chmod +x b1e55ed-forge",
        "forge": f"./b1e55ed-forge --prefix b1e55ed --threads {req.cpu_cores} --json",
        "register_forged": (
            f"curl -X POST https://oracle.b1e55ed.permanentupperclass.com/api/v1/spi/producers/{producer_id}/forge-complete "
            "-H 'Content-Type: application/json' "
            f'-d \'{{"forged_address": "0xb1e55edYOURADDRESS", "signature": "0xYOUR_EIP191_SIGNATURE"}}\''
        ),
        "note": "The private key stays on YOUR machine. You only prove ownership by signing a message.",
    }

    return ForgeEstimateResponse(
        estimated_seconds=estimated_seconds,
        recommendation=recommendation,
        message=message,
        instructions=instructions,
        forge_required=FORGE_REQUIRED,
        grace_period_days=FORGE_GRACE_PERIOD_DAYS,
    )


@router.post(
    "/producers/{producer_id}/forge-complete",
    response_model=ForgeCompleteResponse,
    summary="Link a forged 0xb1e55ed address to a producer",
)
def forge_complete(
    producer_id: str,
    req: ForgeCompleteRequest = Body(...),
    db: Database = Depends(get_db),
) -> ForgeCompleteResponse:
    _ensure_key_column(db)

    forged_address = req.forged_address.strip()
    if not forged_address.lower().startswith(FORGE_PREFIX):
        raise HTTPException(status_code=400, detail="Address must start with 0xb1e55ed")

    producer = db.fetchone(
        "SELECT producer_id FROM spi_producers WHERE producer_id = ?",
        (producer_id,),
    )
    if producer is None:
        raise B1e55edError(
            code="spi.producer_not_found",
            message=f"Producer '{producer_id}' not found",
            status=404,
        )

    message = f"b1e55ed-forge-{producer_id}"
    verified = True

    try:
        from eth_account import Account
        from eth_account.messages import encode_defunct

        msg = encode_defunct(text=message)
        recovered = Account.recover_message(msg, signature=req.signature)
        if recovered.lower() != forged_address.lower():
            raise HTTPException(status_code=400, detail="Signature does not match forged address")
    except ImportError:
        # eth_account not available — skip verification for now.
        verified = False
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Signature verification failed: {exc}") from exc

    now = datetime.now(tz=UTC).isoformat()
    db.execute(
        """
        UPDATE spi_producers
        SET forged_address = ?, forged_at = ?, updated_at = ?
        WHERE producer_id = ?
        """,
        (forged_address, now, now, producer_id),
    )

    success_message = "Identity forged. Your 0xb1e55ed address is now linked to your producer account."
    if not verified:
        success_message = "Identity linked. Signature verification was skipped because eth_account is unavailable on the server."

    return ForgeCompleteResponse(
        producer_id=producer_id,
        forged_address=forged_address,
        verified=verified,
        message=success_message,
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
