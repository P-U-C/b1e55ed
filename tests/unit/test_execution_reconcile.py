"""tests.unit.test_execution_reconcile

Tests for reconcile_execution_events() — the crash-recovery mechanism that
backfills provenance events for positions that were persisted but whose events
were lost (e.g. a process crash between execute_market() and event append).
"""

from __future__ import annotations

import uuid
from pathlib import Path

from engine.core.database import Database
from engine.core.events import EventType
from engine.execution.oms import reconcile_execution_events

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = "2024-01-01T00:00:00"


def _insert_position_and_order(
    db: Database,
    *,
    symbol: str = "BTC",
    direction: str = "long",
) -> tuple[str, str]:
    """Insert a bare position + order directly into the DB, mimicking what
    paper.py commits atomically.  No events are emitted — this simulates the
    crash window where the DB write succeeded but the subsequent event appends
    never ran.

    Returns (position_id, order_id).
    """
    position_id = str(uuid.uuid4())
    order_id = str(uuid.uuid4())
    idem_key = str(uuid.uuid4())
    side = "buy" if direction == "long" else "sell"

    with db._lock, db.conn:
        db.conn.execute(
            """
            INSERT INTO positions (
                id, platform, asset, direction, entry_price, size_notional, leverage,
                stop_loss, take_profit, opened_at, status
            ) VALUES (?, 'paper', ?, ?, 50000.0, 1000.0, 1.0, NULL, NULL, ?, 'open')
            """,
            (position_id, symbol, direction, _NOW),
        )
        db.conn.execute(
            """
            INSERT INTO orders (
                id, position_id, venue, type, side, symbol, size, price,
                fill_price, fill_size, status, idempotency_key,
                created_at, filled_at, updated_at
            ) VALUES (?, ?, 'paper', 'market', ?, ?, 0.02, NULL,
                       50000.0, 0.02, 'filled', ?, ?, ?, ?)
            """,
            (order_id, position_id, side, symbol, idem_key, _NOW, _NOW, _NOW),
        )

    return position_id, order_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_crash_after_position_persist_can_be_reconciled(tmp_path: Path) -> None:
    """After a crash (position+order persisted, no events), reconcile backfills
    ORDER_SUBMITTED_V1, ORDER_FILLED_V1, POSITION_OPENED_V1, and
    SIGNAL_ACCEPTED_V1.
    """
    db = Database(tmp_path / "brain.db")
    _insert_position_and_order(db)

    # Verify no execution events exist yet
    ev_types = [
        EventType.ORDER_SUBMITTED_V1.value,
        EventType.ORDER_FILLED_V1.value,
        EventType.POSITION_OPENED_V1.value,
        EventType.SIGNAL_ACCEPTED_V1.value,
    ]
    placeholders = ",".join("?" * len(ev_types))
    rows_before = db.conn.execute(
        f"SELECT type FROM events WHERE type IN ({placeholders})",
        ev_types,
    ).fetchall()
    assert len(rows_before) == 0, "no execution events should exist before reconcile"

    counts = reconcile_execution_events(db)

    assert counts["order_submitted"] == 1
    assert counts["order_filled"] == 1
    assert counts["position_opened"] == 1
    assert counts["signal_accepted"] == 1

    # Verify events now exist in the DB
    rows_after = db.conn.execute(
        f"SELECT type FROM events WHERE type IN ({placeholders})",
        ev_types,
    ).fetchall()
    assert len(rows_after) == 4


def test_no_duplicate_backfill_events_on_reconcile(tmp_path: Path) -> None:
    """Running reconcile twice produces no additional events (idempotent)."""
    db = Database(tmp_path / "brain.db")
    _insert_position_and_order(db)

    counts1 = reconcile_execution_events(db)
    counts2 = reconcile_execution_events(db)

    # First run: backfilled 4 events
    assert sum(counts1.values()) == 4

    # Second run: zero new events
    assert counts2["order_submitted"] == 0
    assert counts2["order_filled"] == 0
    assert counts2["position_opened"] == 0
    assert counts2["signal_accepted"] == 0
    assert sum(counts2.values()) == 0

    # Total event count is identical after both runs
    total_events = db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    # At least the 4 backfilled events exist; running again didn't add more
    assert total_events >= 4

    counts3 = reconcile_execution_events(db)
    total_events_after_third = db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert total_events_after_third == total_events
    assert sum(counts3.values()) == 0


def test_position_without_signal_accepted_is_repaired(tmp_path: Path) -> None:
    """A position that has ORDER/POSITION events but lacks SIGNAL_ACCEPTED_V1
    is repaired: reconcile emits exactly one SIGNAL_ACCEPTED_V1 and leaves the
    already-present order events untouched.
    """
    db = Database(tmp_path / "brain.db")
    position_id, order_id = _insert_position_and_order(db, symbol="ETH", direction="long")

    # Manually emit ORDER_SUBMITTED, ORDER_FILLED, POSITION_OPENED — but NOT
    # SIGNAL_ACCEPTED — to simulate a partial emission before crash.
    db.append_event(
        event_type=EventType.ORDER_SUBMITTED_V1,
        payload={
            "order_id": order_id,
            "position_id": position_id,
            "venue": "paper",
            "type": "market",
            "side": "buy",
            "symbol": "ETH",
            "size": 0.02,
            "idempotency_key": "test-idem",
        },
        source="test",
        dedupe_key=f"order_submitted:{order_id}",
    )
    db.append_event(
        event_type=EventType.ORDER_FILLED_V1,
        payload={
            "order_id": order_id,
            "position_id": position_id,
            "fill_price": 3000.0,
            "fill_size": 0.02,
            "fee_usd": 0.0,
        },
        source="test",
        dedupe_key=f"order_filled:{order_id}",
    )
    db.append_event(
        event_type=EventType.POSITION_OPENED_V1,
        payload={
            "position_id": position_id,
            "platform": "paper",
            "asset": "ETH",
            "direction": "long",
            "entry_price": 3000.0,
            "size_notional": 60.0,
            "leverage": 1.0,
        },
        source="test",
        dedupe_key=f"position_opened:{position_id}",
    )

    # Verify SIGNAL_ACCEPTED_V1 is absent
    sa_before = db.conn.execute(
        "SELECT id FROM events WHERE type = ?",
        (EventType.SIGNAL_ACCEPTED_V1.value,),
    ).fetchall()
    assert len(sa_before) == 0

    counts = reconcile_execution_events(db)

    # Only signal_accepted should be new; everything else was already present
    assert counts["order_submitted"] == 0
    assert counts["order_filled"] == 0
    assert counts["position_opened"] == 0
    assert counts["signal_accepted"] == 1

    # SIGNAL_ACCEPTED_V1 now exists with the correct trade_id
    sa_after = db.conn.execute(
        "SELECT id FROM events WHERE type = ? AND json_extract(payload, '$.trade_id') = ?",
        (EventType.SIGNAL_ACCEPTED_V1.value, position_id),
    ).fetchall()
    assert len(sa_after) == 1

    # Running reconcile again produces no duplicates
    counts2 = reconcile_execution_events(db)
    assert counts2["signal_accepted"] == 0

    sa_final = db.conn.execute(
        "SELECT id FROM events WHERE type = ?",
        (EventType.SIGNAL_ACCEPTED_V1.value,),
    ).fetchall()
    assert len(sa_final) == 1
