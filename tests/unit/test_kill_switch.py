from __future__ import annotations

import pytest

from engine.brain.kill_switch import KillSwitch, KillSwitchLevel, PauseGate
from engine.brain.orchestrator import BrainOrchestrator
from engine.core.database import Database
from engine.core.events import EventType
from engine.security.identity import generate_node_identity


def test_kill_switch_5_levels_escalates_and_never_auto_deescalates(test_config, temp_dir):
    db = Database(temp_dir / "brain.db")
    ks = KillSwitch(test_config, db)

    assert ks.level == KillSwitchLevel.SAFE

    d1 = ks.evaluate(daily_loss_pct=test_config.kill_switch.l1_daily_loss_pct + 0.01)
    assert d1 is not None
    assert ks.level == KillSwitchLevel.CAUTION

    # Escalate
    d2 = ks.evaluate(portfolio_heat_pct=test_config.kill_switch.l2_portfolio_heat_pct + 0.01)
    assert d2 is not None
    assert ks.level == KillSwitchLevel.DEFENSIVE

    # Attempt to de-escalate by providing safe values does nothing
    d3 = ks.evaluate(daily_loss_pct=0.0, portfolio_heat_pct=0.0, crisis_conditions=0, max_drawdown_pct=0.0)
    assert d3 is None
    assert ks.level == KillSwitchLevel.DEFENSIVE

    # Manual L5
    d5 = ks.evaluate(manual_level=KillSwitchLevel.SHUTDOWN, reason="manual_test")
    assert d5 is not None
    assert ks.level == KillSwitchLevel.SHUTDOWN


def test_crisis_hysteresis_prevents_instant_lockdown(test_config, temp_dir):
    """Crisis must be sustained for l3_crisis_hysteresis cycles before L3."""
    db = Database(temp_dir / "brain.db")
    ks = KillSwitch(test_config, db)
    threshold = test_config.kill_switch.l3_crisis_threshold
    hysteresis = test_config.kill_switch.l3_crisis_hysteresis  # default 3

    # First CRISIS cycle — should NOT escalate yet
    d = ks.evaluate(crisis_conditions=threshold, is_crisis=True, reason="regime_crisis")
    assert d is None
    assert ks.level == KillSwitchLevel.SAFE

    # Second CRISIS cycle — still below hysteresis
    d = ks.evaluate(crisis_conditions=threshold, is_crisis=True, reason="regime_crisis")
    assert d is None
    assert ks.level == KillSwitchLevel.SAFE

    # Third CRISIS cycle — meets hysteresis, should escalate
    d = ks.evaluate(crisis_conditions=threshold, is_crisis=True, reason="regime_crisis")
    assert d is not None
    assert ks.level == KillSwitchLevel.LOCKDOWN


def test_crisis_hysteresis_resets_on_non_crisis(test_config, temp_dir):
    """A non-crisis cycle resets the crisis tick counter."""
    db = Database(temp_dir / "brain.db")
    ks = KillSwitch(test_config, db)
    threshold = test_config.kill_switch.l3_crisis_threshold

    # Two crisis cycles (below hysteresis of 3)
    ks.evaluate(crisis_conditions=threshold, is_crisis=True, reason="regime_crisis")
    ks.evaluate(crisis_conditions=threshold, is_crisis=True, reason="regime_crisis")
    assert ks.level == KillSwitchLevel.SAFE

    # Non-crisis cycle resets counter
    ks.evaluate(is_crisis=False)

    # Need 3 consecutive again
    ks.evaluate(crisis_conditions=threshold, is_crisis=True, reason="regime_crisis")
    ks.evaluate(crisis_conditions=threshold, is_crisis=True, reason="regime_crisis")
    assert ks.level == KillSwitchLevel.SAFE  # still only 2


def test_auto_deescalation_from_lockdown(test_config, temp_dir):
    """L3 auto-de-escalates to L2 after l3_cooldown_cycles non-crisis cycles."""
    db = Database(temp_dir / "brain.db")
    ks = KillSwitch(test_config, db)
    threshold = test_config.kill_switch.l3_crisis_threshold
    hysteresis = test_config.kill_switch.l3_crisis_hysteresis
    cooldown = test_config.kill_switch.l3_cooldown_cycles  # default 6

    # Escalate to L3 via sustained crisis
    for _ in range(hysteresis):
        ks.evaluate(crisis_conditions=threshold, is_crisis=True, reason="regime_crisis")
    assert ks.level == KillSwitchLevel.LOCKDOWN

    # Non-crisis cycles below cooldown — stays at L3
    for i in range(cooldown - 1):
        d = ks.evaluate(is_crisis=False)
        assert d is None, f"unexpected de-escalation at cycle {i+1}"
        assert ks.level == KillSwitchLevel.LOCKDOWN

    # Cooldown met — auto-de-escalate to DEFENSIVE
    d = ks.evaluate(is_crisis=False)
    assert d is not None
    assert d.level == KillSwitchLevel.DEFENSIVE
    assert ks.level == KillSwitchLevel.DEFENSIVE


def test_pause_gate_not_paused_by_default(temp_dir):
    db = Database(temp_dir / "brain.db")
    gate = PauseGate(db)

    paused, reason = gate.is_paused()

    assert paused is False
    assert reason is None


def test_pause_gate_active_after_pause_event(temp_dir):
    db = Database(temp_dir / "brain.db")
    gate = PauseGate(db)

    db.append_event(
        event_type=EventType.PAUSE_V1,
        payload={"reason": "reviewing signals"},
        source="test.pause",
    )

    paused, reason = gate.is_paused()

    assert paused is True
    assert reason == "reviewing signals"


def test_pause_gate_consumed_after_orchestrator_reads(test_config, temp_dir, monkeypatch):
    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "test")

    db = Database(temp_dir / "brain.db")
    db.append_event(
        event_type=EventType.PAUSE_V1,
        payload={"reason": "manual interject"},
        source="test.pause",
    )

    ident = generate_node_identity()
    orch = BrainOrchestrator(test_config, db, ident)

    with pytest.raises(RuntimeError, match="Brain cycle paused: manual interject"):
        orch.run_cycle(["BTC"])

    consumed = db.get_events(event_type=EventType.PAUSE_CONSUMED_V1, limit=1)
    assert consumed

    gate = PauseGate(db)
    paused, reason = gate.is_paused()

    assert paused is False
    assert reason is None


def test_resume_clears_pause(temp_dir):
    db = Database(temp_dir / "brain.db")
    gate = PauseGate(db)

    db.append_event(
        event_type=EventType.PAUSE_V1,
        payload={"reason": "operator pause"},
        source="test.pause",
    )
    paused, reason = gate.is_paused()
    assert paused is True
    assert reason == "operator pause"

    db.append_event(
        event_type=EventType.PAUSE_CONSUMED_V1,
        payload={"consumed_by": "operator", "auto": False},
        source="test.resume",
    )

    paused, reason = gate.is_paused()

    assert paused is False
    assert reason is None
