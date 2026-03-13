from __future__ import annotations

from pathlib import Path

from engine.brain.kill_switch import KillSwitch
from engine.core.config import Config
from engine.core.database import Database
from engine.core.policy import TradingPolicy, TradingPolicyEngine
from engine.core.types import TradeIntent
from engine.execution.oms import OMS, default_sizer_from_config
from engine.execution.preflight import Preflight


def test_submit_intent_paper_creates_fill_and_events(temp_dir: Path, test_config: Config) -> None:
    db = Database(temp_dir / "brain.db")
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
        symbol="BTC",
        direction="long",
        size_pct=0.05,
        leverage=1.0,
        conviction_score=80.0,
        regime="BULL",
        rationale="unit test",
        stop_loss_pct=0.05,
        take_profit_pct=0.10,
    )

    res = oms.submit(intent, mid_price=50_000.0, equity_usd=10_000.0)
    assert res.status == "filled"
    assert res.order_id is not None
    assert res.position_id is not None

    pos = db.conn.execute("SELECT * FROM positions WHERE id = ?", (res.position_id,)).fetchone()
    assert pos is not None
    assert pos["status"] == "open"

    # execution events emitted
    evs = db.get_events(limit=50)
    types = {e.type for e in evs}
    assert "execution.trade_intent.v1" in {str(t) for t in types}
    assert "execution.order_filled.v1" in {str(t) for t in types}


# Terra 2022 compressed this lesson into 72 hours: when direction flips, risk geometry flips with it.
# This test keeps that memory executable.
def test_submit_intent_short_uses_inverted_stop_and_target(temp_dir: Path, test_config: Config) -> None:
    db = Database(temp_dir / "brain.db")
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
        symbol="SOL",
        direction="short",
        size_pct=0.05,
        leverage=1.0,
        conviction_score=80.0,
        regime="BEAR",
        rationale="unit test short",
        stop_loss_pct=0.05,
        take_profit_pct=0.10,
    )

    mid = 100.0
    res = oms.submit(intent, mid_price=mid, equity_usd=10_000.0)
    assert res.status == "filled"
    assert res.position_id is not None

    pos = db.conn.execute("SELECT stop_loss, take_profit FROM positions WHERE id = ?", (res.position_id,)).fetchone()
    assert pos is not None
    # For shorts: stop above entry, target below entry.
    assert float(pos["stop_loss"]) == 105.0
    assert float(pos["take_profit"]) == 90.0
