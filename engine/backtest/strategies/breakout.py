"""engine.backtest.strategies.breakout

Simple breakout (long-only):
- long when close > max(high, lookback)
- flat otherwise

Requires high series; if missing falls back to close.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from engine.backtest.strategies.base import Strategy, StrategyResult


@dataclass(frozen=True, slots=True)
class BreakoutStrategy(Strategy):
    name: str = "breakout"
    lookback: int = 20

    def generate(self, *, close: np.ndarray, high: np.ndarray | None = None, low=None, volume=None) -> StrategyResult:
        t_len = close.shape[0]
        sig = np.zeros(t_len, dtype=np.float64)
        n = int(self.lookback)
        if t_len == 0 or n <= 1:
            return StrategyResult(signal=sig)

        h = high if high is not None else close
        h = h.astype(np.float64)
        # rolling max of previous n bars
        roll = np.full_like(h, np.nan, dtype=np.float64)
        for i in range(n, t_len):
            roll[i] = float(np.max(h[i - n : i]))

        mask = np.isfinite(roll)
        sig[mask & (close > roll)] = 1.0
        return StrategyResult(signal=sig)
