"""engine.backtest.strategies.combined

Combined strategy: momentum OR MA crossover.

This is not the final ensemble logic; it just replaces placeholders
and provides a multi-signal example.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from engine.backtest.strategies.base import Strategy, StrategyResult
from engine.backtest.strategies.ma_crossover import MACrossoverStrategy
from engine.backtest.strategies.momentum import MomentumStrategy


@dataclass(frozen=True, slots=True)
class CombinedStrategy(Strategy):
    name: str = "combined"

    mom_lookback: int = 20
    mom_threshold: float = 0.02

    fast: int = 10
    slow: int = 50

    def generate(self, *, close: np.ndarray, high=None, low=None, volume=None) -> StrategyResult:
        mom = MomentumStrategy(lookback=self.mom_lookback, threshold=self.mom_threshold).generate(close=close).signal
        ma = MACrossoverStrategy(fast=self.fast, slow=self.slow).generate(close=close).signal
        sig = np.clip(mom + ma, 0.0, 1.0)
        return StrategyResult(signal=sig)
