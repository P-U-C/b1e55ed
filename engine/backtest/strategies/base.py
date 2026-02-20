"""engine.backtest.strategies.base

Backtest strategy contract.

A strategy is a pure function over a price series and optional features.
It outputs a position signal per bar.

Signal convention:
- -1.0 = fully short
-  0.0 = flat
- +1.0 = fully long

The simulator translates signals into trades.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class StrategyResult:
    signal: np.ndarray  # float64, shape (T,)


class Strategy:
    name: str = "strategy"

    def generate(self, *, close: np.ndarray, high: np.ndarray | None = None, low: np.ndarray | None = None, volume: np.ndarray | None = None) -> StrategyResult:
        raise NotImplementedError
