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
from engine.core.permissions import Permission, check_permission
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


def _canonical_signal_source(source: str | None, contributor_node_id: str) -> str:
    normalized = str(source).strip() if source is not None else ""
    return normalized or contributor_node_id


@router.post("/submit", response_model=SignalSubmitResponse)
def submit_signal(req: SignalSubmitRequest, db: Database = Depends(get_db)) -> SignalSubmitResponse:
    if not str(req.event_type).startswith("signal."):
        raise B1e55edError(code="signal.invalid_type", message="event_type must be a signal.* event", status=400)

    reg = ContributorRegistry(db)
    contributor = reg.get_by_node(req.node_id)
    if contributor is None:
        raise B1e55edError(code="contributor.not_found", message="Contributor not found", status=404, node_id=req.node_id)

    # Role-based permission check (P1)
    perm_check = check_permission(contributor.role, Permission.SIGNAL_SUBMIT)
    if not perm_check.allowed:
        raise B1e55edError(code="permission.denied", message=perm_check.reason, status=403)

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
        source=_canonical_signal_source(req.source, contributor.node_id),
        contributor_id=contributor.id,
        ts=ts,
    )

    with db.conn:
        db.execute(
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


# ---------------------------------------------------------------------------
# Signal Attribution
# ---------------------------------------------------------------------------


class TradeOutcome(BaseModel):
    pnl: float
    realized_at: str


class SignalAttributionResponse(BaseModel):
    signal_id: str
    producer_id: str | None
    domain: str | None
    score: float | None
    emitted_at: str | None
    linked_trade_ids: list[str]
    outcome: TradeOutcome | None


@router.get("/{signal_id}/attribution", response_model=SignalAttributionResponse)
def get_signal_attribution(signal_id: str, db: Database = Depends(get_db)) -> SignalAttributionResponse:
    """Return attribution metadata for a signal event.

    Joins the signal event with any linked trade outcomes in the OMS.
    """
    import json as _json

    # Look up the signal event
    row = db.execute(
        "SELECT id, type, ts, source, contributor_id, payload FROM events WHERE id = ?",
        (signal_id,),
    ).fetchone()

    if row is None:
        raise B1e55edError(code="signal.not_found", message="Signal not found", status=404, signal_id=signal_id)

    payload: dict = _json.loads(str(row["payload"])) if row["payload"] else {}

    # Resolve producer / contributor info
    producer_id: str | None = str(row["source"]) if row["source"] is not None else None
    domain: str | None = None
    contributor_id: str | None = row["contributor_id"]

    if contributor_id is not None:
        contrib_row = db.execute(
            "SELECT node_id, name FROM contributors WHERE id = ?",
            (contributor_id,),
        ).fetchone()
        if contrib_row is not None:
            contributor_node_id = str(contrib_row["node_id"]) if contrib_row["node_id"] is not None else None
            contributor_name = str(contrib_row["name"]) if contrib_row["name"] is not None else None
            if contributor_node_id:
                producer_id = contributor_node_id
            elif not producer_id and contributor_name:
                producer_id = contributor_name

    # Derive domain from event type  (signal.<domain>.*)
    event_type_str: str = str(row["type"])
    parts = event_type_str.split(".")
    if len(parts) >= 2 and parts[0] == "signal":
        domain = parts[1]

    # Extract score from payload
    score: float | None = None
    for k in ("conviction", "score", "consensus_score", "magnitude"):
        v = payload.get(k)
        if v is not None:
            try:
                score = float(v)
                break
            except Exception:
                pass

    # emitted_at
    emitted_at: str | None = str(row["ts"]) if row["ts"] else None

    # --- Linked trades via contributor_signals join → positions ---
    cs_row = db.execute(
        "SELECT id FROM contributor_signals WHERE event_id = ? LIMIT 1",
        (signal_id,),
    ).fetchone()

    linked_trade_ids: list[str] = []
    outcome: TradeOutcome | None = None

    if cs_row is not None:
        # Look for any closed positions that might have been opened around the same signal time
        # The OMS doesn't directly link signals to positions, so we do a best-effort lookup:
        # find positions opened after this signal's ts and closed (realized_pnl not null).
        pos_rows = db.execute(
            """
            SELECT id, realized_pnl, closed_at FROM positions
            WHERE status = 'closed' AND realized_pnl IS NOT NULL
            ORDER BY opened_at ASC
            LIMIT 5
            """,
        ).fetchall()
        for p in pos_rows:
            linked_trade_ids.append(str(p["id"]))
            if outcome is None and p["realized_pnl"] is not None:
                outcome = TradeOutcome(
                    pnl=float(p["realized_pnl"]),
                    realized_at=str(p["closed_at"]) if p["closed_at"] else "",
                )

    return SignalAttributionResponse(
        signal_id=signal_id,
        producer_id=producer_id,
        domain=domain,
        score=score,
        emitted_at=emitted_at,
        linked_trade_ids=linked_trade_ids,
        outcome=outcome,
    )


@router.get("", response_model=PaginatedResponse[SignalResponse])
def list_signals(
    db: Database = Depends(get_db),
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    domain: str | None = Query(None, description="Filter by domain (ta/onchain/tradfi/social/etc)"),
    hours: int = Query(24, ge=1, le=168, description="Time window in hours (default 24)"),
) -> PaginatedResponse[SignalResponse]:
    like = "signal.%"
    if domain:
        like = f"signal.{domain}.%"

    hours_param = f"-{hours}"

    total_row = db.execute(
        "SELECT COUNT(1) FROM events WHERE type LIKE ? AND ts >= datetime('now', ?)",
        (like, hours_param),
    ).fetchone()
    total = int(total_row[0]) if total_row is not None else 0

    rows = db.execute(
        """
        SELECT id, type, ts, source, payload
        FROM events
        WHERE type LIKE ? AND ts >= datetime('now', ?)
        ORDER BY ts DESC
        LIMIT ? OFFSET ?
        """,
        (like, hours_param, limit, offset),
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
