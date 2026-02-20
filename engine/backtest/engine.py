"""engine.backtest.engine

Backtest entry point.

B1a implements a minimal, correct loop:
- strategy generates a position signal
- simulator converts signal + prices into equity curve
- validation computes metrics

Data ingestion (OHLCV loaders, feature store integration) is intentionally
out of scope for B1a.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from engine.backtest.simulator import SimConfig, SimResult, simulate
from engine.backtest.strategies.base import Strategy
from engine.backtest.validation import Metrics, compute_metrics


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    fee_bps: float = 10.0
    periods_per_year: int = 365


@dataclass(frozen=True, slots=True)
class BacktestResult:
    sim: SimResult
    metrics: Metrics


def run_backtest(
    *,
    strategy: Strategy,
    close: np.ndarray,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    volume: np.ndarray | None = None,
    cfg: BacktestConfig | None = None,
) -> BacktestResult:
    cfg = cfg or BacktestConfig()

    res = strategy.generate(close=close, high=high, low=low, volume=volume)
    sim = simulate(close=close, signal=res.signal, cfg=SimConfig(fee_bps=cfg.fee_bps))
    metrics = compute_metrics(equity=sim.equity, returns=sim.returns, periods_per_year=cfg.periods_per_year)
    return BacktestResult(sim=sim, metrics=metrics)
