"""engine.backtest.strategies.ma_crossover

Moving average crossover:
- long when fast_ma > slow_ma
- flat otherwise

No shorting in v1.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from engine.backtest.strategies.base import Strategy, StrategyResult


def _sma(x: np.ndarray, n: int) -> np.ndarray:
    x = x.astype(np.float64)
    if n <= 1:
        return x
    out = np.full_like(x, np.nan, dtype=np.float64)
    if x.size < n:
        return out

    csum = np.cumsum(x, dtype=np.float64)
    # rolling sum for windows ending at i (inclusive): sum[x[i-n+1:i+1]]
    roll_sum = csum[n - 1 :].copy()
    roll_sum[1:] = roll_sum[1:] - csum[:-n]
    out[n - 1 :] = roll_sum / float(n)
    return out


@dataclass(frozen=True, slots=True)
class MACrossoverStrategy(Strategy):
    name: str = "ma_crossover"
    fast: int = 10
    slow: int = 50

    def generate(self, *, close: np.ndarray, high=None, low=None, volume=None) -> StrategyResult:
        t_len = close.shape[0]
        sig = np.zeros(t_len, dtype=np.float64)
        fast = int(self.fast)
        slow = int(self.slow)
        if t_len == 0 or fast <= 0 or slow <= 0 or fast >= slow:
            return StrategyResult(signal=sig)

        f = _sma(close, fast)
        s = _sma(close, slow)
        mask = np.isfinite(f) & np.isfinite(s)
        sig[mask & (f > s)] = 1.0
        return StrategyResult(signal=sig)
