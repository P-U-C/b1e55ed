"""engine.backtest.strategies.volatility

Volatility filter baseline (long-only):
- compute rolling std of returns
- long when vol < max_vol (avoid chaotic regimes)

This is a toy strategy that demonstrates feature gating.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from engine.backtest.strategies.base import Strategy, StrategyResult


@dataclass(frozen=True, slots=True)
class VolatilityFilterStrategy(Strategy):
    name: str = "volatility"
    lookback: int = 20
    max_vol: float = 0.05

    def generate(self, *, close: np.ndarray, high=None, low=None, volume=None) -> StrategyResult:
        t_len = close.shape[0]
        sig = np.zeros(t_len, dtype=np.float64)
        n = int(self.lookback)
        if t_len == 0 or n <= 2:
            return StrategyResult(signal=sig)

        ret = np.zeros(t_len, dtype=np.float64)
        ret[1:] = (close[1:] / close[:-1]) - 1.0

        vol = np.full(t_len, np.nan, dtype=np.float64)
        for i in range(n, t_len):
            vol[i] = float(np.std(ret[i - n : i], ddof=1))

        mask = np.isfinite(vol)
        sig[mask & (vol < float(self.max_vol))] = 1.0
        return StrategyResult(signal=sig)
