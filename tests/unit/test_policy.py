from __future__ import annotations

from dataclasses import dataclass

import pytest

from engine.core.policy import PolicyViolation, TradingPolicy, TradingPolicyEngine


@dataclass(frozen=True)
class _Intent:
    size_pct: float
    leverage: float
    regime: str


def test_policy_daily_loss_limit_blocks() -> None:
    policy = TradingPolicy(max_daily_loss_usd=100.0)
    eng = TradingPolicyEngine(policy)

    eng.state.record_pnl(-150.0)

    with pytest.raises(PolicyViolation) as e:
        eng.check_daily_loss_limit()

    assert e.value.rule == "daily_loss_limit"


def test_policy_position_size_limit_blocks() -> None:
    policy = TradingPolicy(max_position_size_pct=0.10)  # 10%
    eng = TradingPolicyEngine(policy)

    with pytest.raises(PolicyViolation) as e:
        eng.check_position_size_limit(equity_usd=10_000.0, position_notional_usd=1500.0)

    assert e.value.rule == "position_size_limit"


def test_policy_kill_switch_gate_blocks() -> None:
    policy = TradingPolicy(kill_switch_enabled=True)
    eng = TradingPolicyEngine(policy)

    with pytest.raises(PolicyViolation) as e:
        eng.check_kill_switch(level=2)

    assert e.value.rule == "kill_switch"


def test_policy_leverage_limit_by_regime() -> None:
    policy = TradingPolicy(
        max_leverage_default=5.0,
        max_leverage_by_regime={"risk_off": 2.0},
    )
    eng = TradingPolicyEngine(policy)

    eng.check_leverage_limit(leverage=4.0, regime="neutral")

    with pytest.raises(PolicyViolation) as e:
        eng.check_leverage_limit(leverage=3.0, regime="risk_off")

    assert e.value.rule == "leverage_limit"


def test_policy_pretrade_check_runs_all() -> None:
    policy = TradingPolicy(max_position_size_pct=0.20, max_leverage_default=3.0)
    eng = TradingPolicyEngine(policy)

    intent = _Intent(size_pct=0.10, leverage=3.0, regime="neutral")
    eng.pretrade_check(intent, equity_usd=1000.0, kill_switch_level=0)
