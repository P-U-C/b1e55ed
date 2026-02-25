"""engine.backtest.strategies.funding_arb

Placeholder replacement.

True funding arb requires funding/basis series and execution constraints.
For B1b we implement a trivial strategy that stays flat.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from engine.backtest.strategies.base import Strategy, StrategyResult


@dataclass(frozen=True, slots=True)
class FundingArbStrategy(Strategy):
    name: str = "funding_arb"

    def generate(self, *, close: np.ndarray, high=None, low=None, volume=None) -> StrategyResult:
        return StrategyResult(signal=np.zeros(close.shape[0], dtype=np.float64))
