"""Outcome application — writes resolved outcomes and updates karma ledger."""

from __future__ import annotations

from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from engine.spi.models import SignalOutcome


def apply_outcome(db, outcome: SignalOutcome) -> None:  # noqa: ANN001
    """Write a resolved outcome and update karma. Idempotent via INSERT OR IGNORE."""
    now = datetime.now(tz=UTC).isoformat()

    db.execute(
        """
        INSERT OR IGNORE INTO spi_outcomes (
            outcome_id, signal_id, producer_id, resolved_at, status,
            outcome_label, direction_correct, entry_price, exit_price,
            price_change_pct, resolution_method, brier_component,
            karma_delta, score_delta, chain_hash, event_id, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            outcome.outcome_id,
            outcome.signal_id,
            outcome.producer_id,
            outcome.resolved_at,
            outcome.status,
            outcome.outcome_label,
            int(outcome.direction_correct) if outcome.direction_correct is not None else None,
            outcome.entry_price,
            outcome.exit_price,
            outcome.price_change_pct,
            outcome.resolution_method,
            outcome.brier_component,
            outcome.karma_delta,
            outcome.score_delta,
            outcome.chain_hash,
            outcome.event_id,
            now,
        ),
    )

    # Update the parent signal's status to match the outcome.
    db.execute(
        "UPDATE spi_signals SET status = ?, resolved_at = ?, updated_at = ? WHERE signal_id = ?",
        (outcome.status, outcome.resolved_at, now, outcome.signal_id),
    )
