"""engine.integration.outcome_writer

When a position closes, the system must write its outcome back into the
prediction record that created it.

Responsibilities:
- Look up the conviction score that triggered the trade (positions.conviction_id)
- Compute outcome metrics (PnL, time held, max drawdown)
- Write outcome to conviction_scores table
- Emit a learning outcome event

This is intentionally best-effort: if learning fails, execution must not.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from engine.brain.learning import LearningLoop
from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType
from engine.core.time import utc_now


def write_outcome_for_closed_position(
    *,
    db: Database,
    config: Config,
    position_id: str,
) -> dict[str, Any]:
    """Compute and persist outcome attribution for a closed position."""

    row = db.conn.execute("SELECT * FROM positions WHERE id = ?", (str(position_id),)).fetchone()
    if row is None:
        raise ValueError(f"Unknown position_id: {position_id}")

    if str(row["status"]) != "closed":
        raise ValueError(f"Position {position_id} is not closed")

    realized_pnl = row["realized_pnl"]
    if realized_pnl is None:
        raise ValueError(f"Position {position_id} missing realized_pnl")

    loop = LearningLoop(db=db, config=config)
    attribution = loop.attribute_outcome(position_id=str(position_id), realized_pnl=float(realized_pnl))

    # Write outcome back to conviction score.
    with db.conn:
        db.conn.execute(
            "UPDATE conviction_scores SET outcome = ?, outcome_ts = ? WHERE id = ?",
            (float(attribution.realized_pnl), utc_now().isoformat(), int(attribution.conviction_id)),
        )

    # Emit learning outcome event.
    payload = {
        "position_id": attribution.position_id,
        "conviction_id": attribution.conviction_id,
        "realized_pnl": attribution.realized_pnl,
        "direction_correct": attribution.direction_correct,
        "time_held_hours": attribution.time_held_hours,
        "max_drawdown_pct": attribution.max_drawdown_pct,
        "regime_at_entry": attribution.regime_at_entry,
        "domain_scores_at_entry": attribution.domain_scores_at_entry,
    }

    db.append_event(
        event_type=EventType.LEARNING_OUTCOME_V1,
        payload=payload,
        source="outcome_writer",
        dedupe_key=f"learning:outcome:{attribution.position_id}",
        ts=datetime.now(tz=UTC),
    )

    return payload
