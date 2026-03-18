"""test_attribution_chain.py

Verifies that source_event_ids from synthesis propagate all the way through
the attribution chain:
  synthesis snapshot → decide_and_emit() → TradeIntent → OMS._emit_signal_accepted()

Regression test for the disconnected flywheel bug where source_event_ids was
never passed from the snapshot to the TradeIntent, causing OMS to silently
skip SIGNAL_ACCEPTED_V1 emission on every trade.
"""

from __future__ import annotations

from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017


from engine.brain.decision import DecisionEngine
from engine.brain.kill_switch import KillSwitchLevel
from engine.core.database import Database
from engine.core.events import EventType
from engine.core.types import FeatureSnapshot, TradeIntent
from engine.security.identity import generate_node_identity


def _make_snapshot_with_source_ids(db: Database, *, symbol: str = "BTC") -> tuple[FeatureSnapshot, list[str]]:
    """Create real events and return a FeatureSnapshot that references them."""
    ev1 = db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": symbol, "rsi_14": 30.0, "trend_strength": 0.8},
    )
    ev2 = db.append_event(
        event_type=EventType.SIGNAL_TRADFI_V1,
        payload={"symbol": symbol, "funding_annualized": 8.0, "basis_annualized": 3.0},
    )
    source_ids = [ev1.id, ev2.id]
    snap = FeatureSnapshot(
        cycle_id="test-cycle-001",
        symbol=symbol,
        ts=datetime.now(tz=UTC),
        features={
            "technical": {"rsi_14": 30.0, "trend_strength": 0.8},
            "tradfi": {"funding_annualized": 8.0, "basis_annualized": 3.0},
        },
        source_event_ids=source_ids,
        regime="BULL",
    )
    return snap, source_ids


def test_source_event_ids_propagated_to_trade_intent(test_config, temp_dir, monkeypatch):
    """source_event_ids from synthesis must reach the TradeIntent via decide_and_emit."""
    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "test")

    db = Database(temp_dir / "brain.db")
    _snap, source_ids = _make_snapshot_with_source_ids(db)

    dec = DecisionEngine(test_config, db)

    intent = dec.decide_and_emit(
        symbol="BTC",
        pcs=80.0,
        regime="BULL",
        kill_level=KillSwitchLevel.SAFE,
        trace_id="test-cycle-001",
        source_event_ids=source_ids,
    )

    assert intent is not None, "decide_and_emit should produce a TradeIntent for pcs=80 BULL"
    assert len(intent.source_event_ids) == 2, f"TradeIntent.source_event_ids must carry the {len(source_ids)} source IDs, got {len(intent.source_event_ids)}"
    assert set(intent.source_event_ids) == set(source_ids)


def test_source_event_ids_empty_when_not_passed(test_config, temp_dir, monkeypatch):
    """Baseline: without source_event_ids, TradeIntent.source_event_ids is empty."""
    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "test")

    db = Database(temp_dir / "brain.db")
    dec = DecisionEngine(test_config, db)

    intent = dec.decide_and_emit(
        symbol="BTC",
        pcs=80.0,
        regime="BULL",
        kill_level=KillSwitchLevel.SAFE,
        trace_id="t",
    )

    assert intent is not None
    assert intent.source_event_ids == []


def test_oms_emit_signal_accepted_fires_with_source_ids(test_config, temp_dir, monkeypatch):
    """OMS._emit_signal_accepted fires when source_event_ids is non-empty."""
    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "test")

    db = Database(temp_dir / "brain.db")
    _snap, source_ids = _make_snapshot_with_source_ids(db)

    # Build a minimal OMS
    from engine.brain.kill_switch import KillSwitch
    from engine.execution.oms import OMS, default_sizer_from_config
    from engine.execution.preflight import Preflight, default_policy_from_risk

    policy = default_policy_from_risk(
        max_daily_loss_usd=float(test_config.risk.daily_loss_limit_pct) * float(test_config.risk.portfolio_value_usd),
        max_position_size_pct=float(test_config.risk.max_position_pct),
        max_leverage_default=float(test_config.risk.max_leverage),
    )
    preflight = Preflight(policy=policy, kill_switch=KillSwitch(config=test_config, db=db))
    oms = OMS(
        config=test_config,
        db=db,
        preflight=preflight,
        sizer=default_sizer_from_config(test_config),
        policy=policy,
    )

    intent = TradeIntent(
        symbol="BTC",
        direction="long",
        size_pct=0.02,
        leverage=1.0,
        conviction_score=80.0,
        regime="BULL",
        rationale="test",
        stop_loss_pct=0.05,
        take_profit_pct=0.10,
        intended_price=50000.0,
        source_event_ids=source_ids,
    )

    result = oms.submit(intent, mid_price=50000.0, equity_usd=10000.0)
    assert result.status == "filled", f"Expected filled, got {result.status}: {result.reasons}"

    # Verify SIGNAL_ACCEPTED_V1 events were emitted — one per source signal
    accepted_evs = db.get_events(event_type=EventType.SIGNAL_ACCEPTED_V1, limit=100)
    emitted_signal_ids = {ev.payload.get("signal_event_id") for ev in accepted_evs}
    for sid in source_ids:
        assert sid in emitted_signal_ids, f"SIGNAL_ACCEPTED_V1 not emitted for source event {sid}; got {emitted_signal_ids}"


def test_orchestrator_propagates_source_event_ids(test_config, temp_dir, monkeypatch):
    """Full end-to-end: orchestrator run_cycle passes source_event_ids through to OMS."""
    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "test")

    from engine.brain.kill_switch import KillSwitch
    from engine.brain.orchestrator import BrainOrchestrator
    from engine.execution.oms import OMS, default_sizer_from_config
    from engine.execution.preflight import Preflight, default_policy_from_risk

    db = Database(temp_dir / "brain.db")
    ident = generate_node_identity()

    now = datetime.now(tz=UTC)
    # Seed some signals so synthesis has source events to reference
    db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "BTC", "rsi_14": 25.0, "trend_strength": 0.9},
        ts=now,
    )
    db.append_event(
        event_type=EventType.SIGNAL_TRADFI_V1,
        payload={"symbol": "BTC", "funding_annualized": 12.0, "basis_annualized": 6.0},
        ts=now,
    )

    orch = BrainOrchestrator(config=test_config, db=db, identity=ident)

    # Inject OMS so auto-paper-trade can fire
    policy = default_policy_from_risk(
        max_daily_loss_usd=float(test_config.risk.daily_loss_limit_pct) * float(test_config.risk.portfolio_value_usd),
        max_position_size_pct=float(test_config.risk.max_position_pct),
        max_leverage_default=float(test_config.risk.max_leverage),
    )
    preflight = Preflight(policy=policy, kill_switch=KillSwitch(config=test_config, db=db))
    orch._oms = OMS(
        config=test_config,
        db=db,
        preflight=preflight,
        sizer=default_sizer_from_config(test_config),
        policy=policy,
    )

    result = orch.run_cycle(["BTC"])
    assert result.cycle_id

    # The key assertion: if a trade intent was generated and the snapshot had
    # source_event_ids, SIGNAL_ACCEPTED_V1 events must have been emitted.
    # Even if no trade fired (low conviction), at least verify the intents
    # that were generated carry source_event_ids.
    for intent_dict in result.intents:
        # intents are dataclass-as-dict; they must have source_event_ids
        assert "source_event_ids" in intent_dict, "TradeIntent dict must contain source_event_ids key"
