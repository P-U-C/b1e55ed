"""engine.backtest.strategies.trend_following

Trend following baseline (long-only):
- long when close > SMA(lookback)
- flat otherwise
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from engine.backtest.strategies.base import Strategy, StrategyResult
from engine.backtest.strategies.ma_crossover import _sma


@dataclass(frozen=True, slots=True)
class TrendFollowingStrategy(Strategy):
    name: str = "trend_following"
    lookback: int = 50

    def generate(self, *, close: np.ndarray, high=None, low=None, volume=None) -> StrategyResult:
        t_len = close.shape[0]
        sig = np.zeros(t_len, dtype=np.float64)
        n = int(self.lookback)
        if t_len == 0 or n <= 1:
            return StrategyResult(signal=sig)

        ma = _sma(close, n)
        mask = np.isfinite(ma)
        sig[mask & (close > ma)] = 1.0
        return StrategyResult(signal=sig)
