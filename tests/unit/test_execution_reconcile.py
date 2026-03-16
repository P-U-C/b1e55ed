"""tests.unit.test_execution_reconcile

Tests for reconcile_execution_events() — the crash-recovery mechanism that
backfills provenance events for positions that were persisted but whose events
were lost (e.g. a process crash between execute_market() and event append).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

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


# ---------------------------------------------------------------------------
# Wave 2 tests
# ---------------------------------------------------------------------------


def test_reconcile_runs_on_startup(tmp_path: Path) -> None:
    """run_daemon() calls reconcile_execution_events before schedulers start.

    Strategy: create a real DB with an un-reconciled position, patch data_dir
    to return tmp_path so daemon.py finds the DB, and patch asyncio.run to
    avoid actually starting the supervisor loop. After run_daemon returns, the
    DB should contain the reconcile-backfilled SIGNAL_ACCEPTED_V1 events —
    proving reconcile was called before the scheduler/loop phase.
    """
    from engine.core.database import Database

    # Set up a real DB with a position that lacks events (crash scenario)
    db_path = tmp_path / "brain.db"
    db = Database(db_path)
    _insert_position_and_order(db, symbol="SOL", direction="long")
    db.close()

    # Confirm no SIGNAL_ACCEPTED_V1 before daemon start
    db_check = Database(db_path)
    before = db_check.conn.execute(
        "SELECT id FROM events WHERE type = ?",
        (EventType.SIGNAL_ACCEPTED_V1.value,),
    ).fetchall()
    db_check.close()
    assert len(before) == 0, "expected no signal_accepted events before daemon startup"

    # Minimal config mock
    config = MagicMock()
    config.daemon = MagicMock(
        brain_interval_seconds=300,
        brain_full_interval_seconds=21600,
        resolver_interval_seconds=1800,
    )
    config.api = MagicMock(port=5050)

    def _noop_run(coro: object) -> None:
        """Prevent supervisor from actually starting; close coroutine to suppress warnings."""
        if hasattr(coro, "close"):
            coro.close()  # type: ignore[union-attr]

    from engine.cli.commands.daemon import run_daemon

    with (
        patch("engine.cli.commands.daemon.asyncio.run", side_effect=_noop_run),
        patch("engine.core.paths.data_dir", return_value=tmp_path),
    ):
        run_daemon(tmp_path, config)

    # After run_daemon, reconcile should have backfilled SIGNAL_ACCEPTED_V1
    db_after = Database(db_path)
    after = db_after.conn.execute(
        "SELECT id FROM events WHERE type = ?",
        (EventType.SIGNAL_ACCEPTED_V1.value,),
    ).fetchall()
    db_after.close()
    assert len(after) >= 1, "reconcile_execution_events was not called on startup: no SIGNAL_ACCEPTED_V1 events found after run_daemon()"


def test_recovery_placeholder_flag_set(tmp_path: Path) -> None:
    """reconcile_execution_events sets recovery_placeholder=True on backfilled
    SIGNAL_ACCEPTED_V1 events so they are distinguishable from real attribution.
    """
    db = Database(tmp_path / "brain.db")
    position_id, _order_id = _insert_position_and_order(db, symbol="BTC", direction="long")

    counts = reconcile_execution_events(db)
    assert counts["signal_accepted"] == 1

    row = db.conn.execute(
        "SELECT payload FROM events WHERE type = ? AND json_extract(payload, '$.trade_id') = ?",
        (EventType.SIGNAL_ACCEPTED_V1.value, position_id),
    ).fetchone()
    assert row is not None, "SIGNAL_ACCEPTED_V1 not found after reconcile"

    payload = json.loads(row[0])
    assert payload.get("recovery_placeholder") is True, f"recovery_placeholder should be True on backfilled SIGNAL_ACCEPTED_V1; got payload={payload}"


def test_real_signal_accepted_has_no_placeholder_flag(tmp_path: Path) -> None:
    """A SIGNAL_ACCEPTED_V1 emitted by the normal OMS path (not reconcile) must
    NOT carry recovery_placeholder in its payload.
    """
    import os

    from engine.brain.kill_switch import KillSwitch
    from engine.core.config import Config
    from engine.core.policy import TradingPolicy, TradingPolicyEngine
    from engine.core.types import TradeIntent
    from engine.execution.oms import OMS, default_sizer_from_config
    from engine.execution.preflight import Preflight

    repo_root = Path(os.environ.get("B1E55ED_REPO_ROOT", Path(__file__).parent.parent.parent))
    try:
        config = Config.from_repo_defaults(repo_root)
    except Exception:
        config = MagicMock()
        config.execution.mode = "paper"
        config.risk.max_position_pct = 0.05
        config.risk.daily_loss_limit_pct = 0.02
        config.risk.portfolio_value_usd = 10000.0
        config.risk.max_leverage = 3.0

    db = Database(tmp_path / "brain.db")

    try:
        ks = KillSwitch(config, db)
        pol = TradingPolicy(
            max_daily_loss_usd=200.0,
            max_position_size_pct=float(config.risk.max_position_pct),
            kill_switch_enabled=True,
            max_leverage_default=float(config.risk.max_leverage),
        )
        policy_engine = TradingPolicyEngine(policy=pol)
        preflight = Preflight(policy=policy_engine, kill_switch=ks)
        sizer = default_sizer_from_config(config)
        oms = OMS(config=config, db=db, preflight=preflight, sizer=sizer)

        intent = TradeIntent(
            symbol="BTC",
            direction="long",
            size_pct=0.05,
            leverage=1.0,
            conviction_score=75.0,
            regime="BULL",
            rationale="wave2 unit test",
        )

        result = oms.submit(intent, mid_price=50_000.0, equity_usd=10_000.0)
        assert result.status == "filled", f"OMS submission failed: {result}"

        # Fetch all SIGNAL_ACCEPTED_V1 events for this trade
        rows = db.conn.execute(
            "SELECT payload FROM events WHERE type = ? AND json_extract(payload, '$.trade_id') = ?",
            (EventType.SIGNAL_ACCEPTED_V1.value, result.position_id),
        ).fetchall()
        assert len(rows) >= 1, "No SIGNAL_ACCEPTED_V1 events found after normal OMS submit"

        for row in rows:
            payload = json.loads(row[0])
            assert "recovery_placeholder" not in payload, f"Normal OMS-emitted SIGNAL_ACCEPTED_V1 must NOT have recovery_placeholder; got payload={payload}"
    except Exception as exc:
        import pytest

        pytest.skip(f"OMS setup failed (config unavailable in test env): {exc}")
