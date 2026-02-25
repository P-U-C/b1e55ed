"""engine.backtest.strategies.rsi_reversion

RSI reversion (long-only):
- long when RSI < oversold
- flat when RSI > exit

This is a toy baseline.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from engine.backtest.strategies.base import Strategy, StrategyResult


def _rsi(close: np.ndarray, n: int) -> np.ndarray:
    close = close.astype(np.float64)
    if n <= 1 or close.size == 0:
        return np.full_like(close, np.nan, dtype=np.float64)

    diff = np.diff(close, prepend=close[0])
    up = np.maximum(diff, 0.0)
    down = np.maximum(-diff, 0.0)

    # Wilder smoothing (EMA-like)
    rsi = np.full_like(close, np.nan, dtype=np.float64)
    avg_up = np.mean(up[1 : n + 1])
    avg_down = np.mean(down[1 : n + 1])

    for i in range(n + 1, close.size):
        avg_up = (avg_up * (n - 1) + up[i]) / n
        avg_down = (avg_down * (n - 1) + down[i]) / n
        rs = avg_up / avg_down if avg_down > 0 else np.inf
        rsi[i] = 100.0 - (100.0 / (1.0 + rs))

    return rsi


@dataclass(frozen=True, slots=True)
class RSIReversionStrategy(Strategy):
    name: str = "rsi_reversion"
    period: int = 14
    oversold: float = 30.0
    exit: float = 50.0

    def generate(self, *, close: np.ndarray, high=None, low=None, volume=None) -> StrategyResult:
        t_len = close.shape[0]
        sig = np.zeros(t_len, dtype=np.float64)
        period = int(self.period)
        if t_len == 0 or period <= 1:
            return StrategyResult(signal=sig)

        r = _rsi(close, period)
        in_pos = False
        for i in range(t_len):
            if not np.isfinite(r[i]):
                continue
            if not in_pos and r[i] < float(self.oversold):
                in_pos = True
            elif in_pos and r[i] > float(self.exit):
                in_pos = False
            sig[i] = 1.0 if in_pos else 0.0

        return StrategyResult(signal=sig)
