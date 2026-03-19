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
9. Bias-flip close: conviction flips direction for same (symbol, horizon) → close
10. Bias-flip does NOT trigger when conviction is stale (> 60 min)
11. Bias-flip does NOT trigger when conviction is same direction
12. Bias-flip does NOT trigger when conviction is for different horizon
13. Horizon-expiry close: position open longer than horizon_hours → close
14. Horizon-expiry does NOT trigger when position is younger than horizon
15. Horizon-expiry does NOT trigger when horizon_hours is NULL
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from engine.core.config import Config
from engine.core.database import Database
from engine.execution.pnl import PnLTracker
from engine.execution.position_monitor import monitor_positions

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
    horizon_hours: float | None = None,
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
               size_notional, status, opened_at, platform, horizon_hours)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, 'paper', ?)
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
                horizon_hours,
            ),
        )
    return pos_id


def _insert_conviction(
    db: Database,
    *,
    symbol: str = "BTC",
    direction: str = "short",
    timeframe: str = "4h",
    ts: datetime | None = None,
    magnitude: float = 7.0,
) -> int:
    """Insert a conviction_scores row and return its id."""
    ts_iso = (ts or datetime.now(tz=UTC)).isoformat()
    with db._lock, db.conn:
        cursor = db.conn.execute(
            """
            INSERT INTO conviction_scores
              (node_id, symbol, direction, magnitude, timeframe, ts, commitment_hash)
            VALUES ('test-node', ?, ?, ?, ?, ?, 'test-hash')
            """,
            (symbol, direction, magnitude, timeframe, ts_iso),
        )
        return cursor.lastrowid


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

        for _i in range(3):
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


class TestBiasFlipClose:
    """Bias-flip close: when latest conviction for (symbol, horizon) flips, close."""

    def test_bias_flip_closes_long_when_conviction_flips_short(self, tmp_db: Database, paper_config: Config):
        """BTC long (4h horizon) open → latest conviction says short (4h) → close."""
        pos_id = _insert_position(
            tmp_db,
            asset="BTC",
            direction="long",
            entry_price=100.0,
            stop_loss=90.0,
            take_profit=120.0,
            opened_at=datetime.now(tz=UTC) - timedelta(hours=2),
            horizon_hours=4.0,
        )
        # Insert a recent conviction that says SHORT for BTC on 4h timeframe
        _insert_conviction(
            tmp_db,
            symbol="BTC",
            direction="short",
            timeframe="4h",
            ts=datetime.now(tz=UTC) - timedelta(minutes=10),
        )

        with _mark_price_side_effect(102.0):  # price doesn't matter for bias flip
            stats = monitor_positions(tmp_db, paper_config)

        row = tmp_db.fetchone("SELECT status FROM positions WHERE id = ?", (pos_id,))
        assert row["status"] == "closed"
        assert stats["closed_bias_flip"] == 1

    def test_bias_flip_closes_short_when_conviction_flips_long(self, tmp_db: Database, paper_config: Config):
        """BTC short (4h) open → latest conviction says long (4h) → close."""
        pos_id = _insert_position(
            tmp_db,
            asset="BTC",
            direction="short",
            entry_price=100.0,
            stop_loss=110.0,
            take_profit=90.0,
            opened_at=datetime.now(tz=UTC) - timedelta(hours=1),
            horizon_hours=4.0,
        )
        _insert_conviction(
            tmp_db,
            symbol="BTC",
            direction="long",
            timeframe="4h",
            ts=datetime.now(tz=UTC) - timedelta(minutes=5),
        )

        with _mark_price_side_effect(99.0):
            stats = monitor_positions(tmp_db, paper_config)

        row = tmp_db.fetchone("SELECT status FROM positions WHERE id = ?", (pos_id,))
        assert row["status"] == "closed"
        assert stats["closed_bias_flip"] == 1

    def test_bias_flip_does_not_trigger_on_stale_conviction(self, tmp_db: Database, paper_config: Config):
        """Conviction > 60 min old should NOT trigger a bias flip close."""
        pos_id = _insert_position(
            tmp_db,
            asset="BTC",
            direction="long",
            entry_price=100.0,
            stop_loss=90.0,
            take_profit=120.0,
            opened_at=datetime.now(tz=UTC) - timedelta(hours=2),
            horizon_hours=4.0,
        )
        # Stale conviction: 2 hours old
        _insert_conviction(
            tmp_db,
            symbol="BTC",
            direction="short",
            timeframe="4h",
            ts=datetime.now(tz=UTC) - timedelta(hours=2),
        )

        with _mark_price_side_effect(102.0):
            stats = monitor_positions(tmp_db, paper_config)

        row = tmp_db.fetchone("SELECT status FROM positions WHERE id = ?", (pos_id,))
        assert row["status"] == "open", "Stale conviction should NOT trigger bias flip"
        assert stats["closed_bias_flip"] == 0

    def test_bias_flip_does_not_trigger_on_same_direction(self, tmp_db: Database, paper_config: Config):
        """Conviction same direction as position → no flip, stay open."""
        pos_id = _insert_position(
            tmp_db,
            asset="BTC",
            direction="long",
            entry_price=100.0,
            stop_loss=90.0,
            take_profit=120.0,
            opened_at=datetime.now(tz=UTC) - timedelta(hours=1),
            horizon_hours=4.0,
        )
        _insert_conviction(
            tmp_db,
            symbol="BTC",
            direction="long",  # same direction
            timeframe="4h",
            ts=datetime.now(tz=UTC) - timedelta(minutes=5),
        )

        with _mark_price_side_effect(102.0):
            stats = monitor_positions(tmp_db, paper_config)

        row = tmp_db.fetchone("SELECT status FROM positions WHERE id = ?", (pos_id,))
        assert row["status"] == "open"
        assert stats["closed_bias_flip"] == 0

    def test_bias_flip_does_not_trigger_on_different_horizon(self, tmp_db: Database, paper_config: Config):
        """BTC long on 4h horizon, conviction flips on 24h → different view, no close."""
        pos_id = _insert_position(
            tmp_db,
            asset="BTC",
            direction="long",
            entry_price=100.0,
            stop_loss=90.0,
            take_profit=120.0,
            opened_at=datetime.now(tz=UTC) - timedelta(hours=1),
            horizon_hours=4.0,  # position is 4h
        )
        _insert_conviction(
            tmp_db,
            symbol="BTC",
            direction="short",
            timeframe="24h",  # conviction is 24h — different view
            ts=datetime.now(tz=UTC) - timedelta(minutes=5),
        )

        with _mark_price_side_effect(102.0):
            stats = monitor_positions(tmp_db, paper_config)

        row = tmp_db.fetchone("SELECT status FROM positions WHERE id = ?", (pos_id,))
        assert row["status"] == "open", "Different horizon conviction should NOT trigger bias flip"
        assert stats["closed_bias_flip"] == 0

    def test_bias_flip_skipped_when_no_horizon(self, tmp_db: Database, paper_config: Config):
        """Position without horizon_hours set → bias flip check is skipped entirely."""
        pos_id = _insert_position(
            tmp_db,
            asset="BTC",
            direction="long",
            entry_price=100.0,
            stop_loss=90.0,
            take_profit=120.0,
            opened_at=datetime.now(tz=UTC) - timedelta(hours=1),
            horizon_hours=None,
        )
        _insert_conviction(
            tmp_db,
            symbol="BTC",
            direction="short",
            timeframe="4h",
            ts=datetime.now(tz=UTC) - timedelta(minutes=5),
        )

        with _mark_price_side_effect(102.0):
            stats = monitor_positions(tmp_db, paper_config)

        row = tmp_db.fetchone("SELECT status FROM positions WHERE id = ?", (pos_id,))
        assert row["status"] == "open"
        assert stats["closed_bias_flip"] == 0


class TestHorizonExpiryClose:
    """Horizon-expiry close: position open longer than its horizon_hours → close."""

    def test_horizon_expiry_triggers_when_elapsed(self, tmp_db: Database, paper_config: Config):
        """Position with horizon_hours=4 open for 5h → should be closed."""
        pos_id = _insert_position(
            tmp_db,
            asset="ETH",
            direction="long",
            entry_price=3000.0,
            stop_loss=2800.0,
            take_profit=3500.0,
            opened_at=datetime.now(tz=UTC) - timedelta(hours=5),
            horizon_hours=4.0,
        )

        with _mark_price_side_effect(3100.0):  # in profit — doesn't matter
            stats = monitor_positions(tmp_db, paper_config)

        row = tmp_db.fetchone("SELECT status FROM positions WHERE id = ?", (pos_id,))
        assert row["status"] == "closed"
        assert stats["closed_horizon_expiry"] == 1

    def test_horizon_expiry_triggers_at_loss(self, tmp_db: Database, paper_config: Config):
        """Horizon expiry closes regardless of PnL — even at a loss."""
        pos_id = _insert_position(
            tmp_db,
            asset="ETH",
            direction="long",
            entry_price=3000.0,
            stop_loss=2800.0,  # not triggered at 2900
            take_profit=3500.0,
            opened_at=datetime.now(tz=UTC) - timedelta(hours=25),
            horizon_hours=24.0,
        )

        with _mark_price_side_effect(2900.0):  # at a loss but above stop
            stats = monitor_positions(tmp_db, paper_config)

        row = tmp_db.fetchone("SELECT status, realized_pnl FROM positions WHERE id = ?", (pos_id,))
        assert row["status"] == "closed"
        assert row["realized_pnl"] < 0, "Should close at a loss — horizon doesn't care about PnL"
        assert stats["closed_horizon_expiry"] == 1

    def test_horizon_expiry_does_not_trigger_when_young(self, tmp_db: Database, paper_config: Config):
        """Position younger than horizon_hours → stays open."""
        pos_id = _insert_position(
            tmp_db,
            asset="ETH",
            direction="long",
            entry_price=3000.0,
            stop_loss=2800.0,
            take_profit=3500.0,
            opened_at=datetime.now(tz=UTC) - timedelta(hours=2),
            horizon_hours=4.0,
        )

        with _mark_price_side_effect(3100.0):
            stats = monitor_positions(tmp_db, paper_config)

        row = tmp_db.fetchone("SELECT status FROM positions WHERE id = ?", (pos_id,))
        assert row["status"] == "open", "Position younger than horizon should stay open"
        assert stats["closed_horizon_expiry"] == 0

    def test_horizon_expiry_does_not_trigger_when_null(self, tmp_db: Database, paper_config: Config):
        """Position with horizon_hours=NULL → no expiry, stays open."""
        pos_id = _insert_position(
            tmp_db,
            asset="ETH",
            direction="long",
            entry_price=3000.0,
            stop_loss=2800.0,
            take_profit=3500.0,
            opened_at=datetime.now(tz=UTC) - timedelta(hours=100),
            horizon_hours=None,
        )

        with _mark_price_side_effect(3100.0):
            stats = monitor_positions(tmp_db, paper_config)

        row = tmp_db.fetchone("SELECT status FROM positions WHERE id = ?", (pos_id,))
        assert row["status"] == "open"
        assert stats["closed_horizon_expiry"] == 0

    def test_stop_loss_takes_priority_over_horizon_expiry(self, tmp_db: Database, paper_config: Config):
        """When both stop_loss and horizon_expiry would trigger, stop_loss wins."""
        pos_id = _insert_position(
            tmp_db,
            asset="ETH",
            direction="long",
            entry_price=3000.0,
            stop_loss=2800.0,
            take_profit=3500.0,
            opened_at=datetime.now(tz=UTC) - timedelta(hours=25),
            horizon_hours=24.0,
        )

        with _mark_price_side_effect(2700.0):  # below stop_loss
            stats = monitor_positions(tmp_db, paper_config)

        row = tmp_db.fetchone("SELECT status FROM positions WHERE id = ?", (pos_id,))
        assert row["status"] == "closed"
        # stop_loss is evaluated first, so it should win
        assert stats["closed_stop"] == 1
        assert stats["closed_horizon_expiry"] == 0
