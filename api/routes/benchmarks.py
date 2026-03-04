"""Discretionary signal management API for benchmark producers."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.auth import AuthDep
from api.deps import get_db
from engine.core.database import Database

router = APIRouter(prefix="/benchmarks", dependencies=[AuthDep])


class DiscretionaryRequest(BaseModel):
    symbol: str
    direction: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    expires_in_hours: float | None = 24


class DiscretionaryResponse(BaseModel):
    id: str
    symbol: str
    direction: str
    confidence: float


@router.post("/discretionary", response_model=DiscretionaryResponse)
def create_discretionary_signal(
    body: DiscretionaryRequest,
    db: Database = Depends(get_db),
) -> DiscretionaryResponse:
    sig_id = str(uuid.uuid4())
    now = datetime.now(tz=UTC).isoformat()
    expires = None
    if body.expires_in_hours is not None:
        expires = (datetime.now(tz=UTC) + timedelta(hours=body.expires_in_hours)).isoformat()

    with db.conn:
        db.conn.execute(
            "INSERT INTO discretionary_signals (id, symbol, direction, confidence, reasoning, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sig_id, body.symbol.upper(), body.direction, body.confidence, body.reasoning, now, expires),
        )

    return DiscretionaryResponse(
        id=sig_id,
        symbol=body.symbol.upper(),
        direction=body.direction,
        confidence=body.confidence,
    )
