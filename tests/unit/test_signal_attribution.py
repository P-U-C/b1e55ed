"""Tests for flywheel S1 — signal attribution layer."""

from __future__ import annotations

import pytest

from engine.brain.decision import DecisionContext, DefaultDecisionPolicy
from engine.brain.kill_switch import KillSwitchLevel
from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType
from engine.core.types import TradeIntent


@pytest.fixture
def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    return db


@pytest.fixture
def config():
    return Config()


class TestSourceEventIdsPropagation:
    """Test that source_event_ids flow through synthesis → conviction → decision → TradeIntent."""

    def test_trade_intent_carries_source_event_ids(self):
        ti = TradeIntent(
            symbol="BTC",
            direction="long",
            size_pct=0.05,
            leverage=1.0,
            conviction_score=80.0,
            regime="TRENDING",
            rationale="test",
            source_event_ids=["evt-1", "evt-2", "evt-3"],
        )
        assert ti.source_event_ids == ["evt-1", "evt-2", "evt-3"]

    def test_trade_intent_defaults_empty(self):
        ti = TradeIntent(
            symbol="BTC",
            direction="long",
            size_pct=0.05,
            leverage=1.0,
            conviction_score=80.0,
            regime="TRENDING",
            rationale="test",
        )
        assert ti.source_event_ids == []

    def test_decision_context_carries_source_event_ids(self):
        ctx = DecisionContext(
            symbol="BTC",
            pcs=80.0,
            regime="TRENDING",
            kill_level=KillSwitchLevel.SAFE,
            source_event_ids=["evt-1"],
        )
        assert ctx.source_event_ids == ["evt-1"]

    def test_decision_policy_passes_source_event_ids(self, config):
        policy = DefaultDecisionPolicy(config)
        ctx = DecisionContext(
            symbol="BTC",
            pcs=80.0,
            regime="TRENDING",
            kill_level=KillSwitchLevel.SAFE,
            source_event_ids=["evt-1", "evt-2"],
        )
        intent = policy.decide(ctx)
        assert intent is not None
        assert intent.source_event_ids == ["evt-1", "evt-2"]

    def test_source_event_ids_propagate_through_synthesis(self, db):
        """Verify FeatureSnapshot captures source_event_ids during synthesis."""
        from engine.brain.synthesis import VectorSynthesis

        # Insert a TA signal event
        ev = db.append_event(
            event_type=EventType.SIGNAL_TA_V1,
            payload={"symbol": "BTC", "rsi_14": 55.0, "ema_20": 50000.0},
            source="test.producer",
        )

        synth = VectorSynthesis(config=Config(), db=db)
        snapshot = synth.build_snapshot(cycle_id="test-cycle", symbol="BTC")
        assert ev.id in snapshot.source_event_ids


def _make_oms(db, config):
    """Helper to construct an OMS with all required dependencies."""
    from engine.brain.kill_switch import KillSwitch
    from engine.core.policy import TradingPolicy, TradingPolicyEngine
    from engine.execution.oms import OMS, default_sizer_from_config
    from engine.execution.paper import PaperBroker
    from engine.execution.preflight import Preflight

    ks = KillSwitch(config=config, db=db)
    policy_engine = TradingPolicyEngine(policy=TradingPolicy())
    preflight = Preflight(policy=policy_engine, kill_switch=ks)
    sizer = default_sizer_from_config(config)
    paper = PaperBroker(db=db)
    return OMS(config=config, db=db, preflight=preflight, sizer=sizer, paper_broker=paper)


class TestSignalAcceptedEmission:
    """Test that OMS emits SIGNAL_ACCEPTED_V1 after paper trade."""

    def test_signal_accepted_emitted_on_paper_trade(self, db, config):
        # Insert a signal event so we have a valid source_event_id
        ev = db.append_event(
            event_type=EventType.SIGNAL_TA_V1,
            payload={"symbol": "BTC", "rsi_14": 55.0},
            source="test.ta_producer",
        )

        oms = _make_oms(db, config)

        intent = TradeIntent(
            symbol="BTC",
            direction="long",
            size_pct=0.05,
            leverage=1.0,
            conviction_score=80.0,
            regime="TRENDING",
            rationale="test",
            source_event_ids=[ev.id],
        )

        result = oms.submit(intent, mid_price=50000.0, equity_usd=10000.0)
        assert result.status == "filled"

        # Check SIGNAL_ACCEPTED_V1 was emitted
        accepted_events = db.get_events(event_type=EventType.SIGNAL_ACCEPTED_V1)
        assert len(accepted_events) >= 1

        payload = accepted_events[0].payload
        assert payload["trade_id"] == str(result.position_id)
        assert payload["signal_event_id"] == ev.id
        assert payload["direction"] == "long"
        assert payload["domain"] == "technical"
        assert payload["producer_id"] == "test.ta_producer"

    def test_no_signal_accepted_when_no_source_events(self, db, config):
        oms = _make_oms(db, config)

        intent = TradeIntent(
            symbol="BTC",
            direction="long",
            size_pct=0.05,
            leverage=1.0,
            conviction_score=80.0,
            regime="TRENDING",
            rationale="test",
        )

        result = oms.submit(intent, mid_price=50000.0, equity_usd=10000.0)
        assert result.status == "filled"

        # No SIGNAL_ACCEPTED_V1 should be emitted
        accepted_events = db.get_events(event_type=EventType.SIGNAL_ACCEPTED_V1)
        assert len(accepted_events) == 0
