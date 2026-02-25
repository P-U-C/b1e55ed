from __future__ import annotations

import numpy as np

from engine.backtest.engine import run_backtest
from engine.backtest.strategies import (
    BreakoutStrategy,
    CombinedStrategy,
    FundingArbStrategy,
    MACrossoverStrategy,
    MeanReversionStrategy,
    MomentumStrategy,
    RSIReversionStrategy,
    TrendFollowingStrategy,
    VolatilityFilterStrategy,
)


def test_strategies_smoke_run():
    close = np.linspace(100.0, 110.0, 200).astype(np.float64)
    high = close * 1.01

    strategies = [
        MomentumStrategy(lookback=20, threshold=0.01),
        MACrossoverStrategy(fast=10, slow=50),
        RSIReversionStrategy(period=14, oversold=30, exit=50),
        BreakoutStrategy(lookback=20),
        MeanReversionStrategy(lookback=20, entry_z=1.0, exit_z=0.2),
        TrendFollowingStrategy(lookback=50),
        VolatilityFilterStrategy(lookback=20, max_vol=0.05),
        CombinedStrategy(mom_lookback=20, mom_threshold=0.01, fast=10, slow=50),
        FundingArbStrategy(),
    ]

    for s in strategies:
        res = run_backtest(strategy=s, close=close, high=high)
        assert res.sim.equity.shape[0] == close.shape[0]
