"""SPI signal resolution — determines outcomes for expired signals."""

from __future__ import annotations

import json
import uuid
from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from engine.spi.models import SignalOutcome
from engine.spi.price_feeds import fetch_price_usd
from engine.spi.scoring import compute_brier, compute_karma_delta, determine_direction_correct


def resolve_expired_signals(db, current_epoch: int = 0) -> list[SignalOutcome]:  # noqa: ANN001
    """Find expired accepted signals, fetch prices, compute outcomes, write results.

    Marks each resolved/expired signal's status in spi_signals.
    Updates spi_karma for each resolved signal's producer.
    """
    now = datetime.now(tz=UTC).isoformat()

    # Find signals whose attribution window has closed.
    rows = db.fetchall(
        """
        SELECT signal_id, producer_id, symbol, direction, confidence,
               horizon_hours, attribution_window_start, attribution_window_end
        FROM spi_signals
        WHERE status = 'accepted'
          AND datetime(substr(attribution_window_end, 1, 19)) <= datetime(?)
        """,
        (now[:19],),
    )

    outcomes: list[SignalOutcome] = []
    for row in rows:
        (
            signal_id,
            producer_id,
            symbol,
            direction,
            confidence,
            horizon_hours,
            window_start,
            window_end,
        ) = row

        entry_price = _get_entry_price(db, signal_id)
        exit_price = fetch_price_usd(symbol)

        if entry_price is None or exit_price is None:
            # Can't resolve prices — mark as expired.
            outcome = _write_outcome(
                db,
                signal_id=signal_id,
                producer_id=producer_id,
                status="expired",
                outcome_label=None,
                direction_correct=None,
                entry_price=None,
                exit_price=exit_price,
                price_change_pct=None,
                resolution_method=None,
                brier_component=None,
                karma_delta=None,
            )
            outcomes.append(outcome)
            continue

        price_change_pct = ((exit_price - entry_price) / entry_price) * 100
        direction_correct = determine_direction_correct(direction, price_change_pct)
        brier = compute_brier(confidence, direction_correct)

        # Update karma (apply cluster weight for dedup).
        cluster_weight = _get_cluster_weight(db, signal_id)
        current_karma = _get_running_karma(db, producer_id)
        karma_delta = compute_karma_delta(current_karma, brier) * cluster_weight
        _update_karma(db, producer_id, current_epoch, brier, current_karma + karma_delta)

        outcome = _write_outcome(
            db,
            signal_id=signal_id,
            producer_id=producer_id,
            status="resolved",
            outcome_label="correct" if direction_correct else "incorrect",
            direction_correct=direction_correct,
            entry_price=entry_price,
            exit_price=exit_price,
            price_change_pct=price_change_pct,
            resolution_method="spot",
            brier_component=brier,
            karma_delta=karma_delta,
        )
        outcomes.append(outcome)

        # Phase 2B: check slash conditions after karma update and apply if triggered
        try:
            from engine.spi.slash import apply_slash, check_slash_conditions  # noqa: PLC0415

            for triggered in check_slash_conditions(db, producer_id):
                apply_slash(db, producer_id, triggered["condition"], triggered["severity"])
        except Exception:  # noqa: BLE001
            pass  # never block resolution

    return outcomes


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _get_cluster_weight(db, signal_id: str) -> float:  # noqa: ANN001
    """Get cluster_weight for a signal; defaults to 1.0 (grandfathered)."""
    row = db.fetchone(
        "SELECT cluster_weight FROM spi_signals WHERE signal_id = ?",
        (signal_id,),
    )
    if row and row[0] is not None:
        return float(row[0])
    return 1.0


def _get_entry_price(db, signal_id: str) -> float | None:  # noqa: ANN001
    """Extract entry price from the signal's stored payload JSON, if present."""
    row = db.fetchone(
        "SELECT signal_payload_json FROM spi_signals WHERE signal_id = ?",
        (signal_id,),
    )
    if not row or not row[0]:
        return None
    try:
        payload = json.loads(row[0])
        # Look for entry_price or price in the adapter metadata or root payload.
        price = payload.get("entry_price") or payload.get("price")
        if price is not None:
            return float(price)
        # Try nested _adapter block.
        adapter = payload.get("_adapter", {})
        price = adapter.get("entry_price") or adapter.get("price")
        if price is not None:
            return float(price)
    except (ValueError, TypeError, json.JSONDecodeError):
        pass
    return None


def _get_running_karma(db, producer_id: str) -> float:  # noqa: ANN001
    """Get current running karma for a producer; defaults to 0.5 (neutral)."""
    row = db.fetchone(
        """
        SELECT running_karma FROM spi_karma
        WHERE producer_id = ?
        ORDER BY epoch DESC
        LIMIT 1
        """,
        (producer_id,),
    )
    return float(row[0]) if row else 0.5


def _update_karma(  # noqa: ANN001
    db,
    producer_id: str,
    epoch: int,
    brier: float,
    new_karma: float,
) -> None:
    """Upsert karma row for (producer_id, epoch); accumulates brier within epoch.

    Fix 4: epoch_brier is a running average across all resolved signals in the epoch,
    not an overwrite.  The ON CONFLICT clause computes the incremental mean:
        new_avg = (old_avg * old_count + new_value) / (old_count + 1)
    """
    new_karma = max(0.0, min(1.0, new_karma))
    now = datetime.now(tz=UTC).isoformat()
    db.execute(
        """
        INSERT INTO spi_karma (producer_id, epoch, epoch_brier, epoch_karma,
                               running_karma, resolved_count, updated_at)
        VALUES (?, ?, ?, ?, ?, 1, ?)
        ON CONFLICT(producer_id, epoch) DO UPDATE SET
            epoch_brier = (epoch_brier * resolved_count + excluded.epoch_brier)
                          / (resolved_count + 1),
            epoch_karma = 1.0 - ((epoch_brier * resolved_count + excluded.epoch_brier)
                                  / (resolved_count + 1)),
            running_karma = excluded.running_karma,
            resolved_count = resolved_count + 1,
            updated_at = excluded.updated_at
        """,
        (producer_id, epoch, brier, 1.0 - brier, new_karma, now),
    )


def _write_outcome(  # noqa: ANN001, PLR0913
    db,
    *,
    signal_id: str,
    producer_id: str,
    status: str,
    outcome_label: str | None,
    direction_correct: bool | None,
    entry_price: float | None,
    exit_price: float | None,
    price_change_pct: float | None,
    resolution_method: str | None,
    brier_component: float | None,
    karma_delta: float | None,
) -> SignalOutcome:
    """Write a resolved/expired outcome to spi_outcomes and update signal status."""
    now = datetime.now(tz=UTC).isoformat()
    outcome_id = str(uuid.uuid4())

    outcome = SignalOutcome(
        outcome_id=outcome_id,
        signal_id=signal_id,
        producer_id=producer_id,
        resolved_at=now,
        status=status,
        outcome_label=outcome_label,
        direction_correct=direction_correct,
        entry_price=entry_price,
        exit_price=exit_price,
        price_change_pct=price_change_pct,
        resolution_method=resolution_method,
        brier_component=brier_component,
        karma_delta=karma_delta,
        score_delta=None,
    )

    db.execute(
        """
        INSERT OR IGNORE INTO spi_outcomes (
            outcome_id, signal_id, producer_id, resolved_at, status,
            outcome_label, direction_correct, entry_price, exit_price,
            price_change_pct, resolution_method, brier_component,
            karma_delta, score_delta, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
            now,
        ),
    )

    # Mark signal as resolved/expired.
    db.execute(
        "UPDATE spi_signals SET status = ?, resolved_at = ?, updated_at = ? WHERE signal_id = ?",
        (status, now, now, signal_id),
    )

    # Persist to disk so CLI and other connections can see the resolution.
    db.conn.commit()

    return outcome
