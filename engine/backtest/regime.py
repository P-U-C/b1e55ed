"""engine.backtest.regime

Regime-conditioned backtesting (B1h).

The idea: strategies that "work" across all regimes are usually mediocre.
Strategies that work brilliantly in one regime and sit out others are
the real edge. This module:

1. Classifies each bar into a regime (BULL/BEAR/CRISIS/TRANSITION)
2. Runs walk-forward backtests on regime-filtered subsets
3. Reports per-regime performance so you can match strategies to regimes

Regime classification uses the same indicators as the live detector
(engine/brain/regime.py), applied retroactively to historical data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from engine.backtest.engine import BacktestConfig, run_backtest
from engine.backtest.stats import benjamini_hochberg, bootstrap_p_value_mean_gt_zero
from engine.backtest.strategies.base import Strategy
from engine.backtest.validation import compute_metrics

# ---------------------------------------------------------------------------
# Regime classification for historical bars
# ---------------------------------------------------------------------------

REGIMES = ("BULL", "BEAR", "CRISIS", "TRANSITION")


def classify_regimes(
    *,
    close: np.ndarray,
    rsi_period: int = 14,
    vol_lookback: int = 20,
    vol_crisis_threshold: float = 0.04,
    trend_lookback: int = 50,
) -> np.ndarray:
    """Classify each bar into a regime using price-derived indicators.

    Since historical data may lack funding/basis/F&G, we use price-only
    proxies that approximate the live regime detector:

    - **RSI** (momentum proxy): >60 = bullish signal, <40 = bearish, <25 = crisis
    - **Volatility** (realized vol): >threshold = crisis signal
    - **Trend** (price vs SMA): above = bullish, below = bearish

    Returns an array of regime strings, shape (T,).
    """
    t_len = int(close.shape[0])
    regimes = np.full(t_len, "TRANSITION", dtype=object)

    if t_len < 2:
        return regimes

    c = close.astype(np.float64)

    # --- RSI ---
    rsi = np.full(t_len, 50.0, dtype=np.float64)
    delta = np.diff(c, prepend=c[0])
    gains = np.where(delta > 0, delta, 0.0)
    losses = np.where(delta < 0, -delta, 0.0)

    period = int(rsi_period)
    if period > 0 and t_len > period:
        avg_gain = np.zeros(t_len, dtype=np.float64)
        avg_loss = np.zeros(t_len, dtype=np.float64)
        avg_gain[period] = np.mean(gains[1 : period + 1])
        avg_loss[period] = np.mean(losses[1 : period + 1])
        for i in range(period + 1, t_len):
            avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i]) / period
            avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i]) / period
        for i in range(period, t_len):
            if avg_loss[i] > 0:
                rs = avg_gain[i] / avg_loss[i]
                rsi[i] = 100.0 - (100.0 / (1.0 + rs))

    # --- Realized volatility ---
    # Divide by prior close (not current) — avoids asymmetric return magnitudes
    prior_close = np.concatenate([[c[0]], c[:-1]])
    returns = np.diff(c, prepend=c[0]) / np.maximum(prior_close, 1e-10)
    vol = np.full(t_len, 0.0, dtype=np.float64)
    vl = int(vol_lookback)
    if vl > 0:
        for i in range(vl, t_len):
            vol[i] = float(np.std(returns[i - vl : i], ddof=1))

    # --- Trend (price vs SMA) ---
    tl = int(trend_lookback)
    sma = np.full(t_len, c[0], dtype=np.float64)
    if tl > 0:
        for i in range(tl, t_len):
            sma[i] = float(np.mean(c[i - tl : i]))

    # --- Classification ---
    for i in range(max(period, vl, tl), t_len):
        bull = 0
        bear = 0
        crisis = 0

        if rsi[i] > 60:
            bull += 1
        if rsi[i] < 40:
            bear += 1
        if rsi[i] < 25:
            crisis += 1

        if vol[i] > vol_crisis_threshold:
            crisis += 1
        if vol[i] > vol_crisis_threshold * 0.7:
            bear += 1

        if c[i] > sma[i]:
            bull += 1
        else:
            bear += 1

        if crisis >= 2:
            regimes[i] = "CRISIS"
        elif bull >= 2:
            regimes[i] = "BULL"
        elif bear >= 2:
            regimes[i] = "BEAR"
        else:
            regimes[i] = "TRANSITION"

    return regimes


# ---------------------------------------------------------------------------
# Regime-conditioned backtest results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RegimeResult:
    """Performance of a strategy within a single regime."""

    regime: str
    n_bars: int
    n_trades: int  # approximate: count of signal changes
    total_return: float
    sharpe: float
    max_drawdown: float
    mean_return: float
    p_value: float
    bh_fdr_pass: bool


@dataclass(frozen=True, slots=True)
class RegimeBacktestResult:
    """Full regime-conditioned backtest output."""

    strategy: str
    params: dict[str, Any]
    overall_sharpe: float
    overall_return: float
    regime_results: list[RegimeResult]
    best_regime: str | None  # regime with highest Sharpe (if FDR pass)
    worst_regime: str | None  # regime with lowest Sharpe


def run_regime_backtest(
    *,
    strategy: Strategy,
    close: np.ndarray,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    volume: np.ndarray | None = None,
    cfg: BacktestConfig | None = None,
    n_boot: int = 2000,
    seed: int = 0,
    q: float = 0.05,
    regimes: np.ndarray | None = None,
) -> RegimeBacktestResult:
    """Run a strategy and evaluate performance per regime.

    Steps:
    1. Run the strategy on the full series to get signals
    2. Classify each bar into a regime
    3. Split returns by regime
    4. Compute metrics + p-value per regime
    5. Apply BH-FDR across all regimes

    Parameters
    ----------
    strategy:
        Strategy to evaluate.
    close, high, low, volume:
        Price series.
    cfg:
        Backtest config (fees, etc).
    n_boot:
        Bootstrap samples for p-value.
    seed:
        RNG seed.
    q:
        FDR threshold.
    regimes:
        Pre-computed regime labels (optional). If None, auto-classified.
    """
    c = close.astype(np.float64)

    # Run full backtest
    # Resolve once so periods_per_year is consistent throughout
    resolved_cfg = cfg if cfg is not None else BacktestConfig()
    bt = run_backtest(strategy=strategy, close=c, high=high, low=low, volume=volume, cfg=resolved_cfg)
    full_returns = bt.sim.returns
    full_equity = bt.sim.equity
    full_metrics = compute_metrics(equity=full_equity, returns=full_returns, periods_per_year=resolved_cfg.periods_per_year)

    # Classify regimes
    if regimes is None:
        regimes = classify_regimes(close=c)

    # Split returns by regime and compute per-regime stats
    regime_returns: dict[str, np.ndarray] = {}
    for regime_name in REGIMES:
        mask = regimes == regime_name
        if np.any(mask):
            regime_returns[regime_name] = full_returns[mask]

    # Compute p-values per regime
    p_values: list[float] = []
    partial: list[dict[str, Any]] = []

    for i, regime_name in enumerate(REGIMES):
        rets = regime_returns.get(regime_name)
        if rets is None or rets.size < 5:
            partial.append(
                {
                    "regime": regime_name,
                    "n_bars": 0 if rets is None else int(rets.size),
                    "n_trades": 0,
                    "total_return": 0.0,
                    "sharpe": 0.0,
                    "max_drawdown": 0.0,
                    "mean_return": 0.0,
                    "p_value": 1.0,
                }
            )
            p_values.append(1.0)
            continue

        # Build equity — include rets[0] (first regime bar is often non-zero)
        eq = np.ones(rets.size, dtype=np.float64)
        eq[0] = 1.0 + rets[0]
        for j in range(1, eq.size):
            eq[j] = eq[j - 1] * (1.0 + rets[j])

        metrics = compute_metrics(equity=eq, returns=rets, periods_per_year=resolved_cfg.periods_per_year)

        # Count position changes as proxy for trades
        regime_position = bt.sim.position[regimes == regime_name]
        n_trades = int(np.sum(np.abs(np.diff(regime_position)) > 0.5)) if regime_position.size > 1 else 0

        tr = bootstrap_p_value_mean_gt_zero(rets, n_boot=n_boot, seed=seed + i)
        p_values.append(tr.p_value)

        partial.append(
            {
                "regime": regime_name,
                "n_bars": int(rets.size),
                "n_trades": n_trades,
                "total_return": metrics.total_return,
                "sharpe": metrics.sharpe,
                "max_drawdown": metrics.max_drawdown,
                "mean_return": tr.statistic,
                "p_value": tr.p_value,
            }
        )

    # FDR across all regimes
    fdr_mask = benjamini_hochberg(p_values, q=q)

    regime_results: list[RegimeResult] = []
    for pr, fdr_pass in zip(partial, fdr_mask, strict=True):
        regime_results.append(
            RegimeResult(
                regime=pr["regime"],
                n_bars=pr["n_bars"],
                n_trades=pr["n_trades"],
                total_return=pr["total_return"],
                sharpe=pr["sharpe"],
                max_drawdown=pr["max_drawdown"],
                mean_return=pr["mean_return"],
                p_value=pr["p_value"],
                bh_fdr_pass=bool(fdr_pass),
            )
        )

    # Find best/worst
    valid = [r for r in regime_results if r.n_bars >= 5]
    fdr_passed = [r for r in valid if r.bh_fdr_pass]
    best = max(fdr_passed, key=lambda r: r.sharpe).regime if fdr_passed else None
    worst = min(valid, key=lambda r: r.sharpe).regime if valid else None

    return RegimeBacktestResult(
        strategy=strategy.name,
        params={},  # caller can fill this in
        overall_sharpe=full_metrics.sharpe,
        overall_return=full_metrics.total_return,
        regime_results=regime_results,
        best_regime=best,
        worst_regime=worst,
    )
