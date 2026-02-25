"""engine.backtest.walkforward

Walk-forward validation harness (B1c).

Goal: prevent self-deception.
- Rolling train/test windows
- Optional embargo between train and test
- Strategy evaluated out-of-sample per window

This is single-asset v1.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from engine.backtest.engine import BacktestConfig, BacktestResult, run_backtest
from engine.backtest.strategies.base import Strategy


@dataclass(frozen=True, slots=True)
class Window:
    train_start: int
    train_end: int
    test_start: int
    test_end: int


def build_windows(
    *,
    t_len: int,
    train_size: int,
    test_size: int,
    step_size: int,
    embargo: int = 0,
) -> list[Window]:
    if t_len <= 0:
        return []
    if train_size <= 0 or test_size <= 0 or step_size <= 0:
        raise ValueError("train_size/test_size/step_size must be > 0")

    out: list[Window] = []
    start = 0
    while True:
        train_start = start
        train_end = train_start + train_size
        test_start = train_end + embargo
        test_end = test_start + test_size
        if test_end > t_len:
            break
        out.append(Window(train_start=train_start, train_end=train_end, test_start=test_start, test_end=test_end))
        start += step_size
    return out


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    windows: list[Window]
    window_metrics: list[dict[str, float]]
    combined_oos_equity: np.ndarray
    combined_oos_returns: np.ndarray


def run_walkforward(
    *,
    strategy: Strategy,
    close: np.ndarray,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    volume: np.ndarray | None = None,
    train_size: int,
    test_size: int,
    step_size: int,
    embargo: int = 0,
    cfg: BacktestConfig | None = None,
) -> WalkForwardResult:
    t_len = int(close.shape[0])
    windows = build_windows(t_len=t_len, train_size=train_size, test_size=test_size, step_size=step_size, embargo=embargo)

    # For now strategies have no fit() step; train window is informational.
    # We evaluate OOS by slicing test windows.
    all_returns: list[np.ndarray] = []
    all_equity: list[np.ndarray] = []
    metrics: list[dict[str, float]] = []

    for w in windows:
        test_close = close[w.test_start : w.test_end]
        test_high = high[w.test_start : w.test_end] if high is not None else None
        test_low = low[w.test_start : w.test_end] if low is not None else None
        test_vol = volume[w.test_start : w.test_end] if volume is not None else None

        bt: BacktestResult = run_backtest(strategy=strategy, close=test_close, high=test_high, low=test_low, volume=test_vol, cfg=cfg)
        all_returns.append(bt.sim.returns)
        all_equity.append(bt.sim.equity)
        metrics.append(
            {
                "total_return": float(bt.metrics.total_return),
                "sharpe": float(bt.metrics.sharpe),
                "max_drawdown": float(bt.metrics.max_drawdown),
            }
        )

    if not all_returns:
        return WalkForwardResult(windows=windows, window_metrics=metrics, combined_oos_equity=np.zeros(0), combined_oos_returns=np.zeros(0))

    combined_returns = np.concatenate(all_returns).astype(np.float64)

    # Combine equity by compounding across windows
    eq = np.ones(combined_returns.shape[0], dtype=np.float64)
    for i in range(1, eq.shape[0]):
        eq[i] = eq[i - 1] * (1.0 + combined_returns[i])

    return WalkForwardResult(
        windows=windows,
        window_metrics=metrics,
        combined_oos_equity=eq,
        combined_oos_returns=combined_returns,
    )
