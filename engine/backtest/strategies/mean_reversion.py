"""engine.backtest.strategies.mean_reversion

Z-score mean reversion (long-only):
- compute rolling mean/std of close
- long when z < -entry_z
- exit when z > -exit_z

Toy baseline.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from engine.backtest.strategies.base import Strategy, StrategyResult


def _rolling_mean_std(x: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    x = x.astype(np.float64)
    mu = np.full_like(x, np.nan, dtype=np.float64)
    sd = np.full_like(x, np.nan, dtype=np.float64)
    if n <= 1 or x.size == 0:
        return mu, sd

    for i in range(n, x.size):
        w = x[i - n : i]
        mu[i] = float(np.mean(w))
        sd[i] = float(np.std(w, ddof=1)) if n > 1 else 0.0
    return mu, sd


@dataclass(frozen=True, slots=True)
class MeanReversionStrategy(Strategy):
    name: str = "mean_reversion"
    lookback: int = 20
    entry_z: float = 1.0
    exit_z: float = 0.2

    def generate(self, *, close: np.ndarray, high=None, low=None, volume=None) -> StrategyResult:
        t_len = close.shape[0]
        sig = np.zeros(t_len, dtype=np.float64)
        n = int(self.lookback)
        if t_len == 0 or n <= 2:
            return StrategyResult(signal=sig)

        mu, sd = _rolling_mean_std(close, n)
        in_pos = False
        for i in range(t_len):
            if not np.isfinite(mu[i]) or not np.isfinite(sd[i]) or sd[i] == 0:
                continue
            z = float((close[i] - mu[i]) / sd[i])
            if not in_pos and z < -float(self.entry_z):
                in_pos = True
            elif in_pos and z > -float(self.exit_z):
                in_pos = False
            sig[i] = 1.0 if in_pos else 0.0

        return StrategyResult(signal=sig)
