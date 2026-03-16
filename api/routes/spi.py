"""SPI gateway endpoints — native signal submission by external producers.

External producers authenticate with X-Producer-Key, submit signals, list
their own signals, and query their karma state.  Both this gateway path and
the adapter path call the same accept_signal() so outcomes are identical.
"""

from __future__ import annotations

import contextlib
import hashlib
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field, field_validator

from api.deps import get_db
from api.errors import B1e55edError
from engine.core.database import Database
from engine.spi.admission import _ensure_tables, accept_signal

router = APIRouter(prefix="/spi", tags=["spi"])


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------


def _ensure_key_column(db: Database) -> None:
    """Add api_key_hash column to spi_producers if it doesn't exist yet.

    Called once per connection (guarded by the existing WeakSet in admission).
    Uses a bare try/except because SQLite has no ALTER TABLE … ADD IF NOT EXISTS.
    """
    _ensure_tables(db)  # always ensure base tables first
    with contextlib.suppress(Exception):  # column may already exist
        db.execute("ALTER TABLE spi_producers ADD COLUMN api_key_hash TEXT")


# ---------------------------------------------------------------------------
# Dependency: resolve producer from X-Producer-Key header
# ---------------------------------------------------------------------------


class _ProducerRow:
    """Thin wrapper around the spi_producers row."""

    def __init__(self, row: tuple) -> None:
        self.producer_id: str = str(row[0])
        self.producer_name: str = str(row[1])
        self.lifecycle_state: str = str(row[2])
        self.ingress_mode: str = str(row[3])


def _get_producer(
    x_producer_key: Annotated[str | None, Header(alias="X-Producer-Key")] = None,
    db: Database = Depends(get_db),
) -> _ProducerRow:
    if not x_producer_key:
        raise B1e55edError(
            code="spi.missing_key",
            message="X-Producer-Key header is required",
            status=403,
        )

    _ensure_key_column(db)
    key_hash = hashlib.sha256(x_producer_key.encode()).hexdigest()
    row = db.fetchone(
        "SELECT producer_id, producer_name, lifecycle_state, ingress_mode FROM spi_producers WHERE api_key_hash = ?",
        (key_hash,),
    )
    if row is None:
        raise B1e55edError(
            code="spi.unknown_key",
            message="Unknown producer key",
            status=403,
        )
    return _ProducerRow(row)


ProducerDep = Annotated[_ProducerRow, Depends(_get_producer)]


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class SignalSubmitRequest(BaseModel):
    symbol: str = Field(..., description='Asset symbol e.g. "BTC-USD"')
    direction: str = Field(..., description='"bullish" | "bearish" | "neutral"')
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in [0, 1]")
    horizon_hours: int = Field(..., ge=1, le=8760, description="Forecast horizon in hours")
    client_signal_id: str | None = Field(
        None,
        description="Producer-side idempotency key; auto-generated if omitted",
    )

    @field_validator("direction")
    @classmethod
    def _validate_direction(cls, v: str) -> str:
        allowed = {"bullish", "bearish", "neutral"}
        if v not in allowed:
            msg = f"direction must be one of {allowed}"
            raise ValueError(msg)
        return v


class SignalSubmitResponse(BaseModel):
    signal_id: str
    status: str
    attribution_window_end: str


class SignalListItem(BaseModel):
    signal_id: str
    symbol: str
    direction: str
    confidence: float
    horizon_hours: int
    status: str
    submitted_at: str
    attribution_window_end: str
    client_signal_id: str | None = None


class SignalListResponse(BaseModel):
    signals: list[SignalListItem]
    total: int


class KarmaResponse(BaseModel):
    producer_id: str
    running_karma: float
    epoch: int
    resolved_count: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/signals",
    response_model=SignalSubmitResponse,
    status_code=201,
    summary="Submit a signal",
    description="Submit a forecast signal for the authenticated producer.",
)
def submit_signal(
    body: SignalSubmitRequest,
    producer: ProducerDep,
    db: Database = Depends(get_db),
) -> SignalSubmitResponse:
    client_id = body.client_signal_id or f"{producer.producer_id}:{body.symbol}:{uuid.uuid4()}"

    # Duplicate check: same client_signal_id from same producer → 409
    existing = db.fetchone(
        "SELECT signal_id, attribution_window_end FROM spi_signals WHERE signal_client_id = ? AND producer_id = ?",
        (client_id, producer.producer_id),
    )
    if existing is not None:
        raise B1e55edError(
            code="spi.duplicate_signal",
            message="Duplicate client_signal_id for this producer",
            status=409,
            signal_id=existing[0],
        )

    accepted = accept_signal(
        producer_id=producer.producer_id,
        signal_client_id=client_id,
        submission_id=str(uuid.uuid4()),
        symbol=body.symbol,
        direction=body.direction,
        confidence=body.confidence,
        horizon_hours=body.horizon_hours,
        ingress_mode="native",
        db=db,
    )

    return SignalSubmitResponse(
        signal_id=accepted.signal_id,
        status=accepted.status,
        attribution_window_end=accepted.attribution_window_end,
    )


@router.get(
    "/signals",
    response_model=SignalListResponse,
    summary="List signals for authenticated producer",
)
def list_signals(
    producer: ProducerDep,
    db: Database = Depends(get_db),
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> SignalListResponse:
    _ensure_tables(db)

    params: list = [producer.producer_id]
    where = "producer_id = ?"
    if status:
        where += " AND status = ?"
        params.append(status)

    count_row = db.fetchone(
        f"SELECT COUNT(*) FROM spi_signals WHERE {where}",
        tuple(params),
    )
    total = int(count_row[0]) if count_row else 0

    rows = db.fetchall(
        f"SELECT signal_id, symbol, direction, confidence, horizon_hours, "
        f"status, submitted_at, attribution_window_end, signal_client_id "
        f"FROM spi_signals WHERE {where} "
        f"ORDER BY submitted_at DESC LIMIT ? OFFSET ?",
        tuple(params + [limit, offset]),
    )

    signals = [
        SignalListItem(
            signal_id=str(r[0]),
            symbol=str(r[1]),
            direction=str(r[2]),
            confidence=float(r[3]),
            horizon_hours=int(r[4]),
            status=str(r[5]),
            submitted_at=str(r[6]),
            attribution_window_end=str(r[7]),
            client_signal_id=r[8] if r[8] else None,
        )
        for r in rows
    ]

    return SignalListResponse(signals=signals, total=total)


@router.get(
    "/producers/{producer_id}/karma",
    response_model=KarmaResponse,
    summary="Get karma state for a producer",
)
def get_karma(
    producer_id: str,
    producer: ProducerDep,
    db: Database = Depends(get_db),
) -> KarmaResponse:
    if producer.producer_id != producer_id:
        raise B1e55edError(
            code="spi.forbidden",
            message="Producer key does not match requested producer_id",
            status=403,
        )

    _ensure_tables(db)
    row = db.fetchone(
        "SELECT running_karma, epoch, resolved_count FROM spi_karma WHERE producer_id = ? ORDER BY epoch DESC LIMIT 1",
        (producer_id,),
    )

    if row is None:
        # No karma entries yet — return bootstrap values
        return KarmaResponse(
            producer_id=producer_id,
            running_karma=0.5,
            epoch=0,
            resolved_count=0,
        )

    return KarmaResponse(
        producer_id=producer_id,
        running_karma=float(row[0]),
        epoch=int(row[1]),
        resolved_count=int(row[2]) if row[2] is not None else 0,
    )
