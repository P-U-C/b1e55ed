from __future__ import annotations

import numpy as np

from engine.backtest.stats import benjamini_hochberg, bootstrap_p_value_mean_gt_zero
from engine.backtest.strategies.momentum import MomentumStrategy
from engine.backtest.walkforward import build_windows, run_walkforward


def test_build_windows_basic():
    w = build_windows(t_len=100, train_size=50, test_size=20, step_size=10, embargo=2)
    assert len(w) > 0
    assert w[0].train_start == 0
    assert w[0].train_end == 50
    assert w[0].test_start == 52


def test_walkforward_runs():
    close = np.linspace(100.0, 110.0, 200).astype(np.float64)
    strat = MomentumStrategy(lookback=10, threshold=0.001)
    res = run_walkforward(strategy=strat, close=close, train_size=80, test_size=40, step_size=40, embargo=2)
    assert res.combined_oos_returns.size > 0
    assert res.combined_oos_equity.size == res.combined_oos_returns.size


def test_bootstrap_p_value():
    r = np.array([0.01] * 50, dtype=np.float64)
    tr = bootstrap_p_value_mean_gt_zero(r, n_boot=200, seed=1)
    assert 0.0 <= tr.p_value <= 1.0


def test_bh_fdr_mask():
    p = [0.001, 0.02, 0.2, 0.9]
    mask = benjamini_hochberg(p, q=0.05)
    assert mask[0] is True
    assert mask[-1] is False
