from __future__ import annotations

import numpy as np

from engine.backtest.validation import compute_metrics


def test_validation_max_drawdown():
    equity = np.array([1.0, 1.2, 1.1, 1.3, 1.0], dtype=np.float64)
    returns = np.array([0.0, 0.2, -0.0833, 0.1818, -0.2307], dtype=np.float64)
    m = compute_metrics(equity=equity, returns=returns)
    assert m.max_drawdown < 0
