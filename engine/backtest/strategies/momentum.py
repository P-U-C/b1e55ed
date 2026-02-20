"""engine.backtest.strategies.momentum

Simple momentum strategy:
- long if close / close[n] - 1 > threshold
- flat otherwise

No shorting in v1.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from engine.backtest.strategies.base import Strategy, StrategyResult


@dataclass(frozen=True, slots=True)
class MomentumStrategy(Strategy):
    name: str = "momentum"
    lookback: int = 20
    threshold: float = 0.02

    def generate(self, *, close: np.ndarray, high=None, low=None, volume=None) -> StrategyResult:
        close = close.astype(np.float64)
        t_len = close.shape[0]
        sig = np.zeros(t_len, dtype=np.float64)
        n = int(self.lookback)
        if n >= t_len or n <= 0:
            return StrategyResult(signal=sig)

        mom = (close / np.roll(close, n)) - 1.0
        mom[:n] = 0.0
        sig[mom > float(self.threshold)] = 1.0
        return StrategyResult(signal=sig)
