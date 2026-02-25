"""tests/e2e/test_brain_cycle.py

End-to-end tests for the brain cycle flow.

Tests
-----
1. Initialize DB + event store, seed signals
2. Run orchestrator.run_cycle()
3. Verify conviction event emitted
4. Kill switch: level 0 → cycle runs; direct block test for high level
5. Brain status reflects completed cycle (conviction_scores table populated)
"""

from __future__ import annotations

import pytest

from engine.brain.kill_switch import KillSwitch, KillSwitchLevel
from engine.brain.orchestrator import BrainOrchestrator
from engine.core.database import Database
from engine.core.events import EventType
from engine.security.identity import generate_node_identity

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path):
    d = Database(tmp_path / "brain.db")
    yield d
    d.close()


@pytest.fixture()
def identity():
    return generate_node_identity()


# ---------------------------------------------------------------------------
# Helper: seed minimal signals
# ---------------------------------------------------------------------------


def _seed_signals(db: Database) -> None:
    """Insert the minimum signals needed to get a conviction from the brain."""
    db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "BTC", "rsi_14": 35.0, "trend_strength": 0.7},
        source="test.ta",
    )
    db.append_event(
        event_type=EventType.SIGNAL_TRADFI_V1,
        payload={"symbol": "BTC", "funding_annualized": 10.0, "basis_annualized": 5.0},
        source="test.tradfi",
    )
    db.append_event(
        event_type=EventType.SIGNAL_ONCHAIN_V1,
        payload={"symbol": "BTC", "exchange_netflow_btc": -500.0, "stablecoin_supply_change_pct": 1.2},
        source="test.onchain",
    )


# ---------------------------------------------------------------------------
# 1. Initialize DB + seed signals
# ---------------------------------------------------------------------------


def test_db_initialized_with_event_store(db):
    """Database schema created; events can be appended."""
    ev = db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "ETH", "rsi_14": 50.0},
    )
    assert ev.id is not None
    assert ev.hash is not None and len(ev.hash) == 64


# ---------------------------------------------------------------------------
# 2 + 3. run_cycle() → conviction event emitted
# ---------------------------------------------------------------------------


def test_run_cycle_emits_conviction(db, identity, test_config):
    """A full brain cycle with seeded signals emits at least one conviction event."""
    _seed_signals(db)

    orch = BrainOrchestrator(test_config, db, identity)
    result = orch.run_cycle(["BTC"])

    assert result.cycle_id is not None
    assert "BTC" in result.convictions

    conviction_events = db.get_events(event_type=EventType.CONVICTION_V1, limit=20)
    assert len(conviction_events) >= 1, "At least one conviction event must be emitted"
    # Verify the event has expected fields
    payload = conviction_events[0].payload
    assert "symbol" in payload or "conviction" in payload or "cycle_id" in payload


# ---------------------------------------------------------------------------
# 4a. Kill switch at SAFE (level 0) → cycle runs
# ---------------------------------------------------------------------------


def test_kill_switch_safe_allows_cycle(db, identity, test_config):
    """Kill switch at SAFE level does not block brain cycle execution."""
    _seed_signals(db)

    orch = BrainOrchestrator(test_config, db, identity)
    # Confirm kill switch starts at SAFE
    assert orch.kill_switch.level == KillSwitchLevel.SAFE

    result = orch.run_cycle(["BTC"])
    assert result.cycle_id is not None
    assert result.kill_switch is None  # no escalation when not in CRISIS regime


# ---------------------------------------------------------------------------
# 4b. Kill switch at EMERGENCY → can_open_new_positions = False
# ---------------------------------------------------------------------------


def test_kill_switch_emergency_blocks_new_positions(db, identity, test_config):
    """When kill switch is at EMERGENCY, new positions cannot be opened."""
    ks = KillSwitch(test_config, db)
    ks.evaluate(max_drawdown_pct=test_config.kill_switch.l4_max_drawdown_pct + 0.01)

    assert ks.level >= KillSwitchLevel.EMERGENCY
    assert ks.can_open_new_positions() is False
    assert ks.can_trade() is True  # EMERGENCY still allows trading, SHUTDOWN does not


def test_kill_switch_shutdown_blocks_trading(db, identity, test_config):
    """At SHUTDOWN (L5), even trading is blocked."""
    ks = KillSwitch(test_config, db)
    ks.evaluate(manual_level=KillSwitchLevel.SHUTDOWN)
    assert ks.can_trade() is False


# ---------------------------------------------------------------------------
# 4c. Kill switch persists across restarts (restored from DB)
# ---------------------------------------------------------------------------


def test_kill_switch_restored_from_db(tmp_path, test_config):
    """Kill switch level survives DB reconnect (anti-amnesia test)."""
    db_path = tmp_path / "brain.db"

    db1 = Database(db_path)
    ks1 = KillSwitch(test_config, db1)
    ks1.evaluate(manual_level=KillSwitchLevel.LOCKDOWN, reason="operator test")
    assert ks1.level == KillSwitchLevel.LOCKDOWN
    db1.close()

    # Re-open
    db2 = Database(db_path)
    ks2 = KillSwitch(test_config, db2)
    assert ks2.level == KillSwitchLevel.LOCKDOWN, (
        "Kill switch level must be restored from DB on restart — otherwise the 5-minute cron effectively has no kill switch"
    )
    db2.close()


# ---------------------------------------------------------------------------
# 5. Brain cycle populates conviction_scores table
# ---------------------------------------------------------------------------


def test_cycle_populates_conviction_scores(db, identity, test_config):
    """run_cycle() writes rows to conviction_scores for status tracking."""
    _seed_signals(db)

    orch = BrainOrchestrator(test_config, db, identity)
    orch.run_cycle(["BTC"])

    row_count = db.conn.execute("SELECT COUNT(*) FROM conviction_scores").fetchone()[0]
    assert row_count >= 1, "conviction_scores table must be populated after a cycle"


# ---------------------------------------------------------------------------
# 6. Cycle emits BRAIN_CYCLE_V1 marker event
# ---------------------------------------------------------------------------


def test_cycle_emits_marker_event(db, identity, test_config):
    """run_cycle() must emit a BRAIN_CYCLE_V1 audit marker."""
    _seed_signals(db)

    orch = BrainOrchestrator(test_config, db, identity)
    result = orch.run_cycle(["BTC"])

    cycle_events = db.get_events(event_type=EventType.BRAIN_CYCLE_V1, limit=10)
    assert len(cycle_events) >= 1
    # Cycle ID must match
    matching = [e for e in cycle_events if e.payload.get("cycle_id") == result.cycle_id]
    assert len(matching) == 1, "Marker event must contain the cycle_id"


# ---------------------------------------------------------------------------
# 7. Multiple cycles produce distinct cycle_ids
# ---------------------------------------------------------------------------


def test_multiple_cycles_have_distinct_ids(db, identity, test_config):
    """Each call to run_cycle() must produce a unique cycle_id."""
    _seed_signals(db)

    orch = BrainOrchestrator(test_config, db, identity)
    r1 = orch.run_cycle(["BTC"])
    r2 = orch.run_cycle(["BTC"])

    assert r1.cycle_id != r2.cycle_id, "Each cycle must have a distinct ID"
