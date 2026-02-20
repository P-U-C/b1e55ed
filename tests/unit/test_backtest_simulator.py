from __future__ import annotations

import numpy as np

from engine.backtest.simulator import SimConfig, simulate


def test_simulator_flat_signal_equity_constant():
    close = np.array([100, 101, 99, 100], dtype=np.float64)
    sig = np.zeros_like(close)
    res = simulate(close=close, signal=sig)
    assert float(res.equity[-1]) == 1.0


def test_simulator_fee_on_position_change():
    close = np.array([100, 100, 100, 100], dtype=np.float64)
    sig = np.array([0, 1, 1, 0], dtype=np.float64)
    res = simulate(close=close, signal=sig, cfg=SimConfig(fee_bps=10.0))
    # no price movement, only fees -> equity < 1
    assert float(res.equity[-1]) < 1.0
