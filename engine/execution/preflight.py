"""engine.execution.preflight

Risk preflight checks for both paper and live execution.

Sprint 2A checks:
- gas balance (for live mode)
- position limits
- daily loss limit
- kill switch gate (engine.brain.kill_switch)

The preflight layer is a *hard gate*; it should be deterministic and easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.brain.kill_switch import KillSwitch, KillSwitchLevel
from engine.core.policy import PolicyViolation, TradingPolicy, TradingPolicyEngine


class PreflightError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PreflightResult:
    approved: bool
    reasons: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GasRequirement:
    venue: str
    asset: str
    min_amount: float


class Preflight:
    def __init__(
        self,
        *,
        policy: TradingPolicyEngine,
        kill_switch: KillSwitch,
        gas_requirements: list[GasRequirement] | None = None,
    ) -> None:
        self.policy = policy
        self.kill_switch = kill_switch
        self.gas_requirements = gas_requirements or []

    def check(
        self,
        intent: Any,
        *,
        mode: str,
        equity_usd: float,
        kill_switch_level: int | None = None,
        gas_balances: dict[tuple[str, str], float] | None = None,
    ) -> PreflightResult:
        m = str(mode)
        reasons: list[str] = []
        details: dict[str, Any] = {"mode": m}

        # Kill switch gate (canonical source of truth)
        level = (
            int(kill_switch_level)
            if kill_switch_level is not None
            else int(self.kill_switch.level)
        )
        details["kill_switch_level"] = level
        try:
            self.policy.check_kill_switch(level=level)
        except PolicyViolation as e:
            reasons.append(e.rule)

        # TradingPolicyEngine handles daily loss + position size + leverage
        try:
            self.policy.pretrade_check(intent, equity_usd=float(equity_usd), kill_switch_level=level)
        except PolicyViolation as e:
            reasons.append(e.rule)
            details.setdefault("policy_message", str(e))

        # Gas checks are only meaningful in live mode.
        if m == "live" and self.gas_requirements:
            balances = gas_balances or {}
            for req in self.gas_requirements:
                key = (str(req.venue), str(req.asset))
                have = float(balances.get(key, 0.0))
                details.setdefault("gas", {})[f"{req.venue}:{req.asset}"] = have
                if have + 1e-12 < float(req.min_amount):
                    reasons.append("insufficient_gas")
                    break

        return PreflightResult(approved=(len(reasons) == 0), reasons=reasons, details=details)


def default_policy_from_risk(
    *,
    max_daily_loss_usd: float,
    max_position_size_pct: float,
    max_leverage_default: float,
    max_leverage_by_regime: dict[str, float] | None = None,
    kill_switch_enabled: bool = True,
) -> TradingPolicyEngine:
    """Convenience helper used in tests/wiring."""

    pol = TradingPolicy(
        max_daily_loss_usd=float(max_daily_loss_usd),
        max_position_size_pct=float(max_position_size_pct),
        kill_switch_enabled=bool(kill_switch_enabled),
        max_leverage_default=float(max_leverage_default),
        max_leverage_by_regime=dict(max_leverage_by_regime or {}),
    )
    return TradingPolicyEngine(policy=pol)
