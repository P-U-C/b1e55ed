from __future__ import annotations

from pathlib import Path

import pytest

from engine.brain.kill_switch import KillSwitch, KillSwitchLevel
from engine.core.config import Config
from engine.core.database import Database
from engine.core.policy import TradingPolicy, TradingPolicyEngine
from engine.core.types import TradeIntent
from engine.execution.preflight import GasRequirement, Preflight


def _mk_policy(*, max_daily_loss_usd: float = 0.0, max_position_pct: float = 0.10) -> TradingPolicyEngine:
    pol = TradingPolicy(
        max_daily_loss_usd=max_daily_loss_usd,
        max_position_size_pct=max_position_pct,
        kill_switch_enabled=True,
        max_leverage_default=5.0,
    )
    return TradingPolicyEngine(policy=pol)


def test_preflight_blocks_on_kill_switch(temp_dir: Path, test_config: Config) -> None:
    db = Database(temp_dir / "brain.db")
    ks = KillSwitch(test_config, db)
    policy = _mk_policy()

    preflight = Preflight(policy=policy, kill_switch=ks)

    # manually raise kill switch to DEFENSIVE
    ks.reset(level=KillSwitchLevel.DEFENSIVE)

    intent = TradeIntent(
        symbol="BTC",
        direction="long",
        size_pct=0.05,
        leverage=1.0,
        conviction_score=80.0,
        regime="BULL",
        rationale="",
    )

    res = preflight.check(intent, mode="paper", equity_usd=10_000.0)
    assert res.approved is False
    assert "kill_switch" in res.reasons


def test_preflight_gas_check_live_mode(temp_dir: Path, test_config: Config) -> None:
    db = Database(temp_dir / "brain.db")
    ks = KillSwitch(test_config, db)
    policy = _mk_policy()
    preflight = Preflight(
        policy=policy,
        kill_switch=ks,
        gas_requirements=[GasRequirement(venue="base", asset="ETH", min_amount=0.001)],
    )

    intent = TradeIntent(
        symbol="ETH",
        direction="long",
        size_pct=0.01,
        leverage=1.0,
        conviction_score=60.0,
        regime="BULL",
        rationale="",
    )

    res = preflight.check(
        intent,
        mode="live",
        equity_usd=10_000.0,
        gas_balances={("base", "ETH"): 0.0},
    )
    assert res.approved is False
    assert "insufficient_gas" in res.reasons


def test_rejects_whale_sized_order_for_non_whale(temp_dir: Path, test_config: Config) -> None:
    # Easter egg spec from BUILD_PLAN Phase 4C.
    db = Database(temp_dir / "brain.db")
    ks = KillSwitch(test_config, db)
    policy = _mk_policy(max_position_pct=0.01)
    preflight = Preflight(policy=policy, kill_switch=ks)

    intent = TradeIntent(
        symbol="BTC",
        direction="long",
        size_pct=0.50,  # huge
        leverage=1.0,
        conviction_score=90.0,
        regime="BULL",
        rationale="",
    )

    res = preflight.check(intent, mode="paper", equity_usd=10_000.0)
    assert res.approved is False
    assert "position_size_limit" in res.reasons
