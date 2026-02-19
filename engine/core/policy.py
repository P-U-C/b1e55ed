"""engine.core.policy

Trading policy pre-trade checks.

The rules exist to protect you from yourself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any


class PolicyViolation(Exception):
    def __init__(self, rule: str, message: str):
        self.rule = str(rule)
        self.message = str(message)
        super().__init__(f"Policy violation [{self.rule}]: {self.message}")


@dataclass(frozen=True, slots=True)
class TradingPolicy:
    max_daily_loss_usd: float = 0.0
    max_position_size_pct: float = 0.15
    kill_switch_enabled: bool = True

    max_leverage_default: float = 5.0
    max_leverage_by_regime: dict[str, float] = field(default_factory=dict)

    def max_leverage_for(self, regime: str | None) -> float:
        if not regime:
            return float(self.max_leverage_default)
        return float(self.max_leverage_by_regime.get(str(regime), self.max_leverage_default))


@dataclass(slots=True)
class PolicyState:
    day: date | None = None
    realized_pnl_usd: float = 0.0

    def _ensure_today(self, now: datetime) -> None:
        d = now.date()
        if self.day != d:
            self.day = d
            self.realized_pnl_usd = 0.0

    def record_pnl(self, pnl_usd: float, *, now: datetime | None = None) -> None:
        n = now or datetime.now(tz=UTC)
        if n.tzinfo is None:
            n = n.replace(tzinfo=UTC)
        self._ensure_today(n)
        self.realized_pnl_usd += float(pnl_usd)

    def daily_loss_usd(self, *, now: datetime | None = None) -> float:
        n = now or datetime.now(tz=UTC)
        if n.tzinfo is None:
            n = n.replace(tzinfo=UTC)
        self._ensure_today(n)
        return max(0.0, -self.realized_pnl_usd)


@dataclass
class TradingPolicyEngine:
    policy: TradingPolicy
    state: PolicyState = field(default_factory=PolicyState)

    def check_kill_switch(self, *, level: int = 0) -> None:
        if self.policy.kill_switch_enabled and int(level) > 0:
            raise PolicyViolation("kill_switch", f"kill switch level {int(level)} blocks trading")

    def check_daily_loss_limit(self, *, now: datetime | None = None) -> None:
        limit = float(self.policy.max_daily_loss_usd)
        if limit <= 0:
            return
        loss = self.state.daily_loss_usd(now=now)
        if loss > limit:
            raise PolicyViolation("daily_loss_limit", f"daily loss ${loss:.2f} exceeds limit ${limit:.2f}")

    def check_position_size_limit(self, *, equity_usd: float, position_notional_usd: float) -> None:
        equity = float(equity_usd)
        if equity <= 0:
            return
        max_allowed = equity * float(self.policy.max_position_size_pct)
        if float(position_notional_usd) > max_allowed:
            raise PolicyViolation(
                "position_size_limit",
                f"position ${float(position_notional_usd):.2f} exceeds {self.policy.max_position_size_pct * 100:.1f}% of equity (${max_allowed:.2f})",
            )

    def check_leverage_limit(self, *, leverage: float, regime: str | None = None) -> None:
        lev = float(leverage)
        max_lev = self.policy.max_leverage_for(regime)
        if lev > max_lev:
            raise PolicyViolation("leverage_limit", f"leverage {lev:.2f} exceeds max {max_lev:.2f} for regime={regime}")

    def pretrade_check(
        self,
        intent: Any,
        *,
        equity_usd: float,
        kill_switch_level: int = 0,
        now: datetime | None = None,
    ) -> None:
        self.check_kill_switch(level=kill_switch_level)
        self.check_daily_loss_limit(now=now)

        size_pct = float(intent.size_pct)
        leverage = float(intent.leverage)
        regime = getattr(intent, "regime", None)

        position_notional = float(equity_usd) * size_pct
        self.check_position_size_limit(equity_usd=float(equity_usd), position_notional_usd=position_notional)
        self.check_leverage_limit(leverage=leverage, regime=str(regime) if regime is not None else None)
