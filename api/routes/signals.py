from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from api.auth import AuthDep
from api.deps import get_db
from api.errors import B1e55edError
from api.schemas.common import PaginatedResponse
from api.schemas.signals import SignalResponse
from engine.core.contributors import ContributorRegistry
from engine.core.database import Database
from engine.core.events import EventType
from engine.core.rate_limiter import SignalRateLimiter

router = APIRouter(prefix="/signals", dependencies=[AuthDep])


class SignalSubmitRequest(BaseModel):
    event_type: EventType = Field(..., description="Signal event type")
    ts: str | None = Field(None, description="ISO timestamp; defaults to now")
    node_id: str = Field(..., description="Contributor node_id")
    source: str | None = Field(None, description="Human-readable source")
    payload: dict = Field(default_factory=dict)


class SignalSubmitResponse(BaseModel):
    event_id: str
    contributor_id: str


def _extract_direction(payload: dict) -> str | None:
    for k in ["direction", "trend"]:
        v = payload.get(k)
        if v is None:
            continue
        return str(v)
    return None


def _extract_score(payload: dict) -> float | None:
    for k in ["conviction", "score", "consensus_score", "magnitude"]:
        v = payload.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except Exception:
            return None
    return None


def _extract_asset(payload: dict) -> str | None:
    for k in ["symbol", "asset", "stablecoin"]:
        v = payload.get(k)
        if v is None:
            continue
        return str(v)
    return None


@router.post("/submit", response_model=SignalSubmitResponse)
def submit_signal(req: SignalSubmitRequest, db: Database = Depends(get_db)) -> SignalSubmitResponse:
    if not str(req.event_type).startswith("signal."):
        raise B1e55edError(code="signal.invalid_type", message="event_type must be a signal.* event", status=400)

    reg = ContributorRegistry(db)
    contributor = reg.get_by_node(req.node_id)
    if contributor is None:
        raise B1e55edError(code="contributor.not_found", message="Contributor not found", status=404, node_id=req.node_id)

    # Rate limiting & anti-spam (S2)
    limiter = SignalRateLimiter(db)
    asset = _extract_asset(req.payload)
    direction = _extract_direction(req.payload)
    check = limiter.check(contributor_id=contributor.id, asset=asset, direction=direction)
    if not check.allowed:
        raise B1e55edError(
            code="signal.rate_limited",
            message=check.reason,
            status=429,
            retry_after=check.retry_after_seconds,
        )

    ts = None
    if req.ts:
        ts = _parse_dt(req.ts)

    ev = db.append_event(
        event_type=req.event_type,
        payload=req.payload,
        source=req.source,
        contributor_id=contributor.id,
        ts=ts,
    )

    with db.conn:
        db.conn.execute(
            """
            INSERT INTO contributor_signals (contributor_id, event_id, signal_direction, signal_score, signal_asset)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                contributor.id,
                ev.id,
                _extract_direction(req.payload),
                _extract_score(req.payload),
                _extract_asset(req.payload),
            ),
        )

    return SignalSubmitResponse(event_id=ev.id, contributor_id=contributor.id)


def _parse_dt(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


@router.get("", response_model=PaginatedResponse[SignalResponse])
def list_signals(
    db: Database = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    domain: str | None = Query(None, description="Filter by domain (ta/onchain/tradfi/social/etc)"),
) -> PaginatedResponse[SignalResponse]:
    like = "signal.%"
    if domain:
        like = f"signal.{domain}.%"

    total_row = db.conn.execute(
        "SELECT COUNT(1) FROM events WHERE type LIKE ?",
        (like,),
    ).fetchone()
    total = int(total_row[0]) if total_row is not None else 0

    rows = db.conn.execute(
        """
        SELECT id, type, ts, source, payload
        FROM events
        WHERE type LIKE ?
        ORDER BY ts DESC
        LIMIT ? OFFSET ?
        """,
        (like, limit, offset),
    ).fetchall()

    items: list[SignalResponse] = []
    import json

    for r in rows:
        items.append(
            SignalResponse(
                id=str(r[0]),
                type=str(r[1]),
                ts=_parse_dt(str(r[2])),
                source=str(r[3]) if r[3] is not None else None,
                payload=json.loads(str(r[4])) if r[4] is not None else {},
            )
        )

    return PaginatedResponse(items=items, limit=limit, offset=offset, total=total)
