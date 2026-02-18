from __future__ import annotations

from engine.execution.position_sizer import CorrelationAwareSizer, KellyParams, PositionSizer


def test_kelly_fraction_non_negative() -> None:
    s = PositionSizer(kelly=KellyParams(p=0.51, b=1.0, fraction_multiplier=0.5))
    assert s.kelly_fraction() >= 0.0


def test_correlation_aware_sizing_reduces_with_corr_and_heat() -> None:
    base = PositionSizer(kelly=KellyParams(p=0.6, b=1.5, fraction_multiplier=0.5))
    s = CorrelationAwareSizer(base)

    a = s.size_usd(equity_usd=10_000, conviction_score=1.0, corr_to_portfolio=0.0, portfolio_heat_pct=0.5)
    b = s.size_usd(equity_usd=10_000, conviction_score=1.0, corr_to_portfolio=1.0, portfolio_heat_pct=0.5)

    assert a >= b
    assert b >= 0.0
