"""api.routes.producers_feedback

Producer Feedback Channel — the brain tells a producer which of its recent
signals were accurate vs missed.

This is a read-only analytics endpoint.  No writes are performed.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.auth import AuthDep
from api.deps import get_db
from engine.core.database import Database

router = APIRouter(prefix="/producers", tags=["producers"], dependencies=[AuthDep])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class FeedbackRequest(BaseModel):
    window_hours: int = Field(24, ge=1, le=720, description="Look-back window in hours (1–720)")


class MissEntry(BaseModel):
    signal_id: str
    signal_type: str
    score: float | None
    outcome: str  # "no_fill" | "loss" | "breakeven" | "unknown"


class FeedbackResponse(BaseModel):
    producer_id: str
    window_hours: int
    signals_evaluated: int
    hit_rate: float
    top_miss: list[MissEntry]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_score(payload: dict[str, Any]) -> float | None:
    for k in ("conviction", "score", "consensus_score", "magnitude", "strength"):
        v = payload.get(k)
        if v is not None:
            try:
                return float(v)
            except Exception:
                pass
    return None


def _determine_outcome(signal_ts: str, db: Database) -> str:
    """Very lightweight outcome determination.

    We look for any POSITION_OPENED event that occurred within 5 minutes of
    the signal timestamp. If found, we check whether the position was eventually
    closed with a positive realized_pnl.

    If no correlated position is found the outcome is "no_fill".
    """
    try:
        sig_dt = datetime.fromisoformat(signal_ts.replace("Z", "+00:00"))
    except Exception:
        return "unknown"

    window_start = (sig_dt - timedelta(seconds=300)).isoformat()
    window_end = (sig_dt + timedelta(seconds=300)).isoformat()

    pos_row = db.conn.execute(
        """
        SELECT payload FROM events
        WHERE type = 'execution.position_opened.v1'
          AND ts BETWEEN ? AND ?
        ORDER BY ts ASC
        LIMIT 1
        """,
        (window_start, window_end),
    ).fetchone()

    if pos_row is None:
        return "no_fill"

    pos_payload = json.loads(str(pos_row[0]))
    position_id = pos_payload.get("position_id")
    if not position_id:
        return "no_fill"

    # Check realized PnL
    pnl_row = db.conn.execute(
        "SELECT realized_pnl FROM positions WHERE id = ? LIMIT 1",
        (position_id,),
    ).fetchone()

    if pnl_row is None:
        return "unknown"

    pnl = pnl_row[0]
    if pnl is None:
        return "unknown"
    pnl_f = float(pnl)
    if pnl_f > 0:
        return "profit"
    if pnl_f < 0:
        return "loss"
    return "breakeven"


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/{producer_id}/feedback", response_model=FeedbackResponse)
def producer_feedback(
    producer_id: str,
    body: FeedbackRequest,
    db: Database = Depends(get_db),
) -> FeedbackResponse:
    """Return accuracy feedback for a producer's recent signals.

    Cross-references signal events from ``producer_id`` with OMS trade
    outcomes to compute a hit rate and surface the top misses.
    """
    cutoff = (datetime.now(tz=UTC) - timedelta(hours=body.window_hours)).isoformat()

    # Fetch signals emitted by this producer within the window.
    # The source field is set to the producer name during ingestion.
    rows = db.conn.execute(
        """
        SELECT id, type, ts, payload
        FROM events
        WHERE type LIKE 'signal.%'
          AND source = ?
          AND ts >= ?
        ORDER BY ts DESC
        LIMIT 500
        """,
        (producer_id, cutoff),
    ).fetchall()

    if not rows:
        # Producer registered but no signals in window — valid empty response
        return FeedbackResponse(
            producer_id=producer_id,
            window_hours=body.window_hours,
            signals_evaluated=0,
            hit_rate=0.0,
            top_miss=[],
        )

    hits = 0
    misses: list[MissEntry] = []

    for r in rows:
        sig_id = str(r[0])
        sig_type = str(r[1])
        sig_ts = str(r[2])
        payload = json.loads(str(r[3]))
        score = _extract_score(payload)

        outcome = _determine_outcome(sig_ts, db)

        if outcome == "profit":
            hits += 1
        else:
            misses.append(
                MissEntry(
                    signal_id=sig_id,
                    signal_type=sig_type,
                    score=score,
                    outcome=outcome,
                )
            )

    total = len(rows)
    hit_rate = hits / total if total > 0 else 0.0

    # Sort misses: signals with a score first (highest score = most costly miss)
    misses.sort(key=lambda m: (m.score is None, -(m.score or 0.0)))

    return FeedbackResponse(
        producer_id=producer_id,
        window_hours=body.window_hours,
        signals_evaluated=total,
        hit_rate=round(hit_rate, 4),
        top_miss=misses[:10],
    )
