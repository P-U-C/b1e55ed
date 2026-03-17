"""tests/test_position_monitor.py

Unit tests for engine.execution.position_monitor.

Tests:
1. stop_loss triggers a position close (short: price rises above stop)
2. take_profit triggers a position close (short: price falls below target)
3. Long stop_loss triggers a position close (long: price falls below stop)
4. Time-based stop: position open > 72h AND losing > 5% → close
5. Time-based stop does NOT trigger when position is < 72h old
6. Time-based stop does NOT trigger when position is not losing > 5%
7. No close when neither stop nor time-stop condition is met
8. consecutive_loss_count = 2 does NOT block new trades (kill switch stays SAFE)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from engine.core.config import Config
from engine.core.database import Database
from engine.execution.pnl import PnLTracker
from engine.execution.position_monitor import (
    monitor_positions,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "test_monitor.db")
    return db


@pytest.fixture()
def paper_config(tmp_path: Path) -> Config:
    config = Config(
        data_dir=str(tmp_path / "data"),
        config_dir=str(tmp_path / "config"),
    )
    return config


def _insert_position(
    db: Database,
    *,
    asset: str = "SOL",
    direction: str = "short",
    entry_price: float = 89.23,
    stop_loss: float | None = 98.21,
    take_profit: float | None = 84.82,
    opened_at: datetime | None = None,
    size_notional: float = 449.0,
) -> str:
    """Insert a fake open position directly and return its ID."""
    import uuid

    pos_id = str(uuid.uuid4())
    opened_at_iso = (opened_at or datetime.now(tz=UTC)).isoformat()
    with db._lock, db.conn:
        db.execute(
            """
            INSERT INTO positions
              (id, asset, direction, entry_price, stop_loss, take_profit,
               size_notional, status, opened_at, platform)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, 'paper')
            """,
            (
                pos_id,
                asset,
                direction,
                entry_price,
                stop_loss,
                take_profit,
                size_notional,
                opened_at_iso,
            ),
        )
    return pos_id


def _mark_price_side_effect(price: float):
    """Return a mock that patches resolve_mark_price to return *price*."""
    return patch(
        "engine.execution.position_monitor.resolve_mark_price",
        return_value=price,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStopLoss:
    def test_short_stop_loss_triggers_close(self, tmp_db: Database, paper_config: Config):
        """Short position: price rises above stop_loss → should be closed."""
        pos_id = _insert_position(
            tmp_db,
            direction="short",
            entry_price=89.23,
            stop_loss=98.21,
            take_profit=84.82,
        )

        # Price ABOVE stop → stop_loss triggered for short
        with _mark_price_side_effect(99.0):
            stats = monitor_positions(tmp_db, paper_config)

        row = tmp_db.fetchone("SELECT status, realized_pnl FROM positions WHERE id = ?", (pos_id,))
        assert row["status"] == "closed", "Position should be closed after stop_loss"
        assert row["realized_pnl"] < 0, "Short stop_loss should produce a loss"
        assert stats["closed_stop"] == 1
        assert stats["errors"] == 0

    def test_long_stop_loss_triggers_close(self, tmp_db: Database, paper_config: Config):
        """Long position: price falls below stop_loss → should be closed."""
        pos_id = _insert_position(
            tmp_db,
            direction="long",
            entry_price=100.0,
            stop_loss=92.0,  # 8% below entry
            take_profit=120.0,
        )

        # Price BELOW stop → stop_loss triggered for long
        with _mark_price_side_effect(90.0):
            stats = monitor_positions(tmp_db, paper_config)

        row = tmp_db.fetchone("SELECT status, realized_pnl FROM positions WHERE id = ?", (pos_id,))
        assert row["status"] == "closed"
        assert row["realized_pnl"] < 0
        assert stats["closed_stop"] == 1


class TestTakeProfit:
    def test_short_take_profit_triggers_close(self, tmp_db: Database, paper_config: Config):
        """Short position: price falls below take_profit → should be closed."""
        pos_id = _insert_position(
            tmp_db,
            direction="short",
            entry_price=89.23,
            stop_loss=98.21,
            take_profit=84.82,
        )

        # Price BELOW take_profit for short → profit
        with _mark_price_side_effect(83.0):
            stats = monitor_positions(tmp_db, paper_config)

        row = tmp_db.fetchone("SELECT status, realized_pnl FROM positions WHERE id = ?", (pos_id,))
        assert row["status"] == "closed"
        assert row["realized_pnl"] > 0, "Short take_profit should produce a gain"
        assert stats["closed_target"] == 1

    def test_long_take_profit_triggers_close(self, tmp_db: Database, paper_config: Config):
        """Long position: price rises above take_profit → should be closed."""
        pos_id = _insert_position(
            tmp_db,
            direction="long",
            entry_price=100.0,
            stop_loss=92.0,
            take_profit=120.0,
        )

        with _mark_price_side_effect(121.0):
            stats = monitor_positions(tmp_db, paper_config)

        row = tmp_db.fetchone("SELECT status, realized_pnl FROM positions WHERE id = ?", (pos_id,))
        assert row["status"] == "closed"
        assert row["realized_pnl"] > 0
        assert stats["closed_target"] == 1


class TestTimeStop:
    def test_time_stop_triggers_when_old_and_losing(self, tmp_db: Database, paper_config: Config):
        """Position > 72h old and losing > 5% → time-based stop fires."""
        old_open = datetime.now(tz=UTC) - timedelta(hours=80)
        pos_id = _insert_position(
            tmp_db,
            direction="short",
            entry_price=89.23,
            stop_loss=98.21,  # not triggered ($94 < $98.21)
            take_profit=84.82,  # not triggered ($94 > $84.82)
            opened_at=old_open,
        )

        # Price slightly above entry — stop not hit, but losing > 5% and open > 72h
        mark_price = 89.23 * 1.06  # 6% adverse move for short
        with _mark_price_side_effect(mark_price):
            stats = monitor_positions(tmp_db, paper_config)

        row = tmp_db.fetchone("SELECT status FROM positions WHERE id = ?", (pos_id,))
        assert row["status"] == "closed", "Time-based stop should have fired"
        assert stats["closed_time_stop"] == 1
        assert stats["closed_stop"] == 0

    def test_time_stop_does_not_trigger_when_young(self, tmp_db: Database, paper_config: Config):
        """Position < 72h old should NOT be time-stopped even if losing."""
        young_open = datetime.now(tz=UTC) - timedelta(hours=24)
        pos_id = _insert_position(
            tmp_db,
            direction="short",
            entry_price=89.23,
            stop_loss=98.21,
            take_profit=84.82,
            opened_at=young_open,
        )

        mark_price = 89.23 * 1.06  # 6% adverse
        with _mark_price_side_effect(mark_price):
            stats = monitor_positions(tmp_db, paper_config)

        row = tmp_db.fetchone("SELECT status FROM positions WHERE id = ?", (pos_id,))
        assert row["status"] == "open", "Young position should NOT be time-stopped"
        assert stats["closed_time_stop"] == 0

    def test_time_stop_does_not_trigger_when_small_loss(self, tmp_db: Database, paper_config: Config):
        """Position > 72h but loss < 5% should NOT be time-stopped."""
        old_open = datetime.now(tz=UTC) - timedelta(hours=100)
        pos_id = _insert_position(
            tmp_db,
            direction="short",
            entry_price=89.23,
            stop_loss=98.21,
            take_profit=84.82,
            opened_at=old_open,
        )

        mark_price = 89.23 * 1.03  # only 3% adverse — below 5% threshold
        with _mark_price_side_effect(mark_price):
            stats = monitor_positions(tmp_db, paper_config)

        row = tmp_db.fetchone("SELECT status FROM positions WHERE id = ?", (pos_id,))
        assert row["status"] == "open", "Small-loss old position should NOT be time-stopped"
        assert stats["closed_time_stop"] == 0

    def test_no_close_when_no_condition_met(self, tmp_db: Database, paper_config: Config):
        """Position with no stop/target/time-stop condition → stays open."""
        pos_id = _insert_position(
            tmp_db,
            direction="short",
            entry_price=89.23,
            stop_loss=98.21,
            take_profit=84.82,
            opened_at=datetime.now(tz=UTC) - timedelta(hours=10),
        )

        # Price between stop and take_profit: no trigger
        with _mark_price_side_effect(94.0):
            stats = monitor_positions(tmp_db, paper_config)

        row = tmp_db.fetchone("SELECT status FROM positions WHERE id = ?", (pos_id,))
        assert row["status"] == "open"
        assert stats["closed_stop"] == 0
        assert stats["closed_target"] == 0
        assert stats["closed_time_stop"] == 0


class TestConsecutiveLossGate:
    def test_two_losses_do_not_escalate_kill_switch(self, tmp_db: Database, paper_config: Config):
        """consecutive_loss_count = 2 should NOT escalate the kill switch to DEFENSIVE.

        The kill switch only escalates at count >= 3, and paper mode bypasses even
        that escalation when paper_ignore_consecutive_loss_gate=True.
        """
        from engine.brain.kill_switch import KillSwitch, KillSwitchLevel

        # Pre-seed consecutive_loss_count = 2
        with tmp_db._lock, tmp_db.conn:
            tmp_db.execute("INSERT OR REPLACE INTO system_state (key, value, updated_at) VALUES ('consecutive_loss_count', '2', datetime('now'))")

        ks = KillSwitch(paper_config, tmp_db)
        assert ks.level == KillSwitchLevel.SAFE, "Kill switch should be SAFE with consecutive_loss_count=2; DEFENSIVE only triggers at count >= 3"

    def test_paper_mode_bypasses_kill_switch_at_three_losses(self, tmp_db: Database, paper_config: Config):
        """In paper mode, 3 consecutive losses should NOT escalate the kill switch."""
        from engine.brain.kill_switch import KillSwitch, KillSwitchLevel

        # Force 3 paper losses by closing a position 3 times through PnLTracker
        pnl = PnLTracker(tmp_db, paper_config)

        for _ in range(3):
            pos_id = _insert_position(
                tmp_db,
                direction="long",
                entry_price=100.0,
                stop_loss=90.0,
                take_profit=120.0,
                asset="BTC",
            )
            # Close at a loss (below entry for long)
            pnl.close_position(position_id=pos_id, exit_price=88.0, reason="test_loss")

        ks = KillSwitch(paper_config, tmp_db)
        # In paper mode with paper_ignore_consecutive_loss_gate=True (default),
        # the kill switch must stay at SAFE.
        assert ks.level == KillSwitchLevel.SAFE, (
            "Paper mode with paper_ignore_consecutive_loss_gate=True should not escalate kill switch even after 3 consecutive losses"
        )
