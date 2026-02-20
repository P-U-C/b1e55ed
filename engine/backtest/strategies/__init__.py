"""engine.backtest.strategies

Strategy library (B1).

These are intentionally simple baselines. The goal is correctness and
comparability, not sophistication.
"""

from engine.backtest.strategies.base import Strategy, StrategyResult
from engine.backtest.strategies.breakout import BreakoutStrategy
from engine.backtest.strategies.combined import CombinedStrategy
from engine.backtest.strategies.funding_arb import FundingArbStrategy
from engine.backtest.strategies.ma_crossover import MACrossoverStrategy
from engine.backtest.strategies.mean_reversion import MeanReversionStrategy
from engine.backtest.strategies.momentum import MomentumStrategy
from engine.backtest.strategies.rsi_reversion import RSIReversionStrategy
from engine.backtest.strategies.trend_following import TrendFollowingStrategy
from engine.backtest.strategies.volatility import VolatilityFilterStrategy

__all__ = [
    "Strategy",
    "StrategyResult",
    "BreakoutStrategy",
    "CombinedStrategy",
    "FundingArbStrategy",
    "MACrossoverStrategy",
    "MeanReversionStrategy",
    "MomentumStrategy",
    "RSIReversionStrategy",
    "TrendFollowingStrategy",
    "VolatilityFilterStrategy",
]
