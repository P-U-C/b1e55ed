from __future__ import annotations

import numpy as np

from engine.backtest.engine import run_backtest
from engine.backtest.strategies.momentum import MomentumStrategy


def test_backtest_runs_and_metrics():
    close = np.array([100, 101, 102, 103, 104, 103, 105], dtype=np.float64)
    strat = MomentumStrategy(lookback=2, threshold=0.005)
    res = run_backtest(strategy=strat, close=close)

    assert res.sim.equity.shape[0] == close.shape[0]
    assert isinstance(res.metrics.total_return, float)
    assert isinstance(res.metrics.sharpe, float)
    assert isinstance(res.metrics.max_drawdown, float)


def test_backtest_empty_series():
    close = np.array([], dtype=np.float64)
    strat = MomentumStrategy(lookback=2, threshold=0.01)
    res = run_backtest(strategy=strat, close=close)
    assert res.sim.equity.size == 0
    assert res.metrics.total_return == 0.0
