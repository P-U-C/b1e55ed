"""engine.backtest.validation

Performance metrics + walk-forward helpers.

This is v1: enough to prevent self-deception.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class Metrics:
    total_return: float
    sharpe: float
    max_drawdown: float


def _max_drawdown(equity: np.ndarray) -> float:
    if equity.size == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    dd = (equity / peak) - 1.0
    return float(dd.min())


def sharpe(returns: np.ndarray, *, periods_per_year: int = 365) -> float:
    r = returns.astype(np.float64)
    if r.size < 2:
        return 0.0
    mu = float(np.mean(r))
    sd = float(np.std(r, ddof=1))
    if sd == 0.0:
        return 0.0
    return (mu / sd) * np.sqrt(periods_per_year)


def compute_metrics(*, equity: np.ndarray, returns: np.ndarray, periods_per_year: int = 365) -> Metrics:
    if equity.size == 0:
        return Metrics(total_return=0.0, sharpe=0.0, max_drawdown=0.0)
    total_return = float(equity[-1] - 1.0)
    return Metrics(
        total_return=total_return,
        sharpe=sharpe(returns, periods_per_year=periods_per_year),
        max_drawdown=_max_drawdown(equity),
    )
