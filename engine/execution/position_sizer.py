"""engine.execution.position_sizer

Position sizing primitives.

Sprint 2A requirements:
- Kelly criterion sizing
- correlation-aware adjustment

This module intentionally avoids coupling to exchange/venue specifics.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KellyParams:
    """Inputs for Kelly sizing.

    - ``p``: probability of winning (0..1)
    - ``b``: payoff ratio (avg win / avg loss), must be > 0

    Kelly fraction: (b*p - (1-p)) / b
    """

    p: float = 0.55
    b: float = 1.2
    fraction_multiplier: float = 0.5  # half-Kelly by default


@dataclass(frozen=True, slots=True)
class RiskLimits:
    max_position_pct: float = 0.10
    min_position_usd: float = 10.0


class PositionSizer:
    def __init__(self, *, kelly: KellyParams | None = None, limits: RiskLimits | None = None) -> None:
        self.kelly = kelly or KellyParams()
        self.limits = limits or RiskLimits()

    def kelly_fraction(self) -> float:
        p = max(0.0, min(1.0, float(self.kelly.p)))
        b = max(1e-9, float(self.kelly.b))
        q = 1.0 - p
        f = (b * p - q) / b
        f = max(0.0, f)
        return float(f) * float(self.kelly.fraction_multiplier)

    def size_usd(
        self,
        *,
        equity_usd: float,
        conviction_score: float,
        max_position_pct: float | None = None,
    ) -> float:
        """Compute a notional position size (USD).

        This combines:
        - half-Kelly (risk / expectancy)
        - conviction scaling: conviction 0..1 scales between 0.25..1.0

        Conviction is treated as a *soft* scaling layer, not a source of leverage.
        """

        eq = max(0.0, float(equity_usd))
        if eq <= 0:
            return 0.0

        # Conviction scaling (0..1) -> (0.25..1.0)
        c = max(0.0, min(1.0, float(conviction_score)))
        scale = 0.25 + 0.75 * c

        raw_fraction = self.kelly_fraction() * scale
        cap_pct = float(max_position_pct) if max_position_pct is not None else float(self.limits.max_position_pct)
        raw_fraction = min(raw_fraction, cap_pct)

        notional = eq * raw_fraction
        if notional < float(self.limits.min_position_usd):
            return 0.0
        return float(notional)


class CorrelationAwareSizer:
    """Wrap a base sizer with correlation-aware throttling.

    The idea: if you're already long high-beta/correlated exposure, new correlated
    longs should be sized down.

    Inputs:
    - ``corr_to_portfolio``: abs correlation of the *new* trade with the existing portfolio, 0..1
    - ``portfolio_heat_pct``: current total exposure / equity, 0..1

    Adjustment multiplier = max(0.0, 1 - corr_to_portfolio * portfolio_heat_pct)
    """

    def __init__(self, base: PositionSizer) -> None:
        self.base = base

    def size_usd(
        self,
        *,
        equity_usd: float,
        conviction_score: float,
        corr_to_portfolio: float = 0.0,
        portfolio_heat_pct: float = 0.0,
        max_position_pct: float | None = None,
    ) -> float:
        base_size = self.base.size_usd(
            equity_usd=equity_usd, conviction_score=conviction_score, max_position_pct=max_position_pct
        )
        if base_size <= 0:
            return 0.0

        corr = max(0.0, min(1.0, abs(float(corr_to_portfolio))))
        heat = max(0.0, min(1.0, float(portfolio_heat_pct)))
        mult = max(0.0, 1.0 - corr * heat)
        sized = base_size * mult

        if sized < float(self.base.limits.min_position_usd):
            return 0.0
        return float(sized)
