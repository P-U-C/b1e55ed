"""Tests for TRADE_INTENT_V1 event semantics.

TRADE_INTENT_V1 must be emitted exactly once per trade decision — by
engine.brain.decision.DecisionEngine.  The OMS (engine.execution.oms)
must NOT emit a second copy.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from engine.brain.decision import DecisionEngine
from engine.brain.kill_switch import KillSwitch, KillSwitchLevel
from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType
from engine.core.policy import TradingPolicy, TradingPolicyEngine
from engine.core.types import TradeIntent
from engine.execution import oms as oms_module
from engine.execution.oms import OMS, default_sizer_from_config
from engine.execution.preflight import Preflight


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    return Database(db_path=tmp_path / "test.db")


@pytest.fixture()
def test_config(tmp_path: Path) -> Config:
    import shutil

    repo_root = Path(__file__).resolve().parents[2]
    cfg_src = repo_root / "config" / "default.yaml"
    cfg_dst_dir = tmp_path / "config"
    cfg_dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cfg_src, cfg_dst_dir / "default.yaml")
    shutil.copytree(repo_root / "config" / "presets", cfg_dst_dir / "presets")
    c = Config.from_yaml(cfg_dst_dir / "default.yaml")
    return c.model_copy(update={"data_dir": tmp_path / "data", "config_dir": cfg_dst_dir})


# ---------------------------------------------------------------------------
# Test 1 — DecisionEngine emits exactly one TRADE_INTENT_V1
# ---------------------------------------------------------------------------


def test_one_trade_intent_event_per_decision(db: Database, test_config: Config) -> None:
    """DecisionEngine.decide_and_emit must produce exactly one TRADE_INTENT_V1 event."""
    engine = DecisionEngine(config=test_config, db=db)

    result = engine.decide_and_emit(
        symbol="BTCUSDT",
        pcs=75.0,
        regime="BULL",
        kill_level=KillSwitchLevel.SAFE,
        source="test.semantics",
    )

    # The decision engine should have returned an intent (pcs=75 → strong conviction)
    assert result is not None, "Expected a TradeIntent to be returned"

    events = db.get_events(event_type=EventType.TRADE_INTENT_V1, limit=100)
    assert len(events) == 1, f"Expected exactly 1 TRADE_INTENT_V1, got {len(events)}"
    assert events[0].payload["symbol"] == "BTCUSDT"


# ---------------------------------------------------------------------------
# Test 2 — OMS.submit does not emit TRADE_INTENT_V1
# ---------------------------------------------------------------------------


def test_oms_submit_does_not_duplicate_trade_intent(db: Database, test_config: Config) -> None:
    """OMS.submit must not emit TRADE_INTENT_V1 (that belongs to decision.py only)."""
    # Static source inspection — fastest and most reliable gate
    submit_source = inspect.getsource(oms_module.OMS.submit)
    assert "TRADE_INTENT_V1" not in submit_source, "OMS.submit must not reference TRADE_INTENT_V1; remove the duplicate emission from engine/execution/oms.py"

    # Runtime confirmation: submit an intent and count events
    ks = KillSwitch(test_config, db)
    pol = TradingPolicy(
        max_daily_loss_usd=0.0,
        max_position_size_pct=test_config.risk.max_position_pct,
        kill_switch_enabled=True,
        max_leverage_default=test_config.risk.max_leverage,
    )
    policy_engine = TradingPolicyEngine(policy=pol)
    preflight = Preflight(policy=policy_engine, kill_switch=ks)
    sizer = default_sizer_from_config(test_config)
    oms = OMS(config=test_config, db=db, preflight=preflight, sizer=sizer)

    intent = TradeIntent(
        symbol="ETHUSDT",
        direction="long",
        size_pct=0.05,
        leverage=1.0,
        conviction_score=80.0,
        regime="BULL",
        rationale="test_oms_no_duplicate",
        stop_loss_pct=0.05,
        take_profit_pct=0.10,
    )

    oms.submit(
        intent,
        mid_price=3000.0,
        equity_usd=10_000.0,
    )

    trade_intent_events = db.get_events(event_type=EventType.TRADE_INTENT_V1, limit=100)
    assert len(trade_intent_events) == 0, (
        f"OMS.submit emitted {len(trade_intent_events)} TRADE_INTENT_V1 event(s); it must emit zero — decision.py is the sole emitter"
    )
