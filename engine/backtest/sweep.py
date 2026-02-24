"""engine.backtest.sweep

Parameter grid sweep + FDR correction across the whole grid (B1e).

Usage pattern
-------------
::

    config = GridConfig(
        strategy="momentum",
        params={"lookback": [10, 20, 50], "threshold": [0.01, 0.02]},
    )
    result = run_grid_sweep(
        config=config,
        close=prices.close,
        train_size=180, test_size=60, step_size=60,
        q=0.05,
    )

The key statistical property: BH-FDR is applied *across all parameter
combinations simultaneously*.  A single-combo test at q=0.05 rejects
5 % of true nulls; sweeping 30 combos without correction rejects ~79 %.
Correcting once across the whole grid keeps FDR ≤ q.
"""

from __future__ import annotations

import dataclasses
import hashlib
import itertools
from dataclasses import dataclass
from typing import Any

import numpy as np

from engine.backtest.engine import BacktestConfig
from engine.backtest.stats import benjamini_hochberg, bootstrap_p_value_mean_gt_zero
from engine.backtest.strategies.base import Strategy
from engine.backtest.walkforward import run_walkforward

# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GridConfig:
    """Specification for a parameter grid sweep."""

    strategy: str  # strategy name (maps to a class via STRATEGY_REGISTRY)
    params: dict[str, list[Any]]  # param_name -> list of candidate values


@dataclass(frozen=True, slots=True)
class GridResult:
    """Result for a single parameter combination."""

    strategy: str
    params: dict[str, Any]  # the specific param combo used
    oos_total_return: float
    oos_sharpe: float
    oos_max_drawdown: float
    mean_return: float
    p_value: float
    bh_fdr_pass: bool  # True iff survived BH-FDR correction across ALL grid combos


@dataclass(frozen=True, slots=True)
class SweepResult:
    """Aggregated results for a full grid sweep."""

    items: list[GridResult]
    total_configs: int
    fdr_survivors: int
    q: float


@dataclass(frozen=True, slots=True)
class MultiSweepResult:
    """Aggregated results for a multi-strategy mega sweep.

    FDR is applied across ALL strategies × ALL parameter combos simultaneously.
    """

    items: list[GridResult]
    total_configs: int
    fdr_survivors: int
    q: float
    strategies_tested: list[str]


# ---------------------------------------------------------------------------
# Strategy registry + instantiation helper
# ---------------------------------------------------------------------------

# Lazy import keeps parse-time weight low; populated on first call.
_STRATEGY_REGISTRY: dict[str, type[Strategy]] | None = None


def _get_registry() -> dict[str, type[Strategy]]:
    global _STRATEGY_REGISTRY
    if _STRATEGY_REGISTRY is None:
        from engine.backtest.strategies.breakout import BreakoutStrategy
        from engine.backtest.strategies.combined import CombinedStrategy
        from engine.backtest.strategies.ma_crossover import MACrossoverStrategy
        from engine.backtest.strategies.mean_reversion import MeanReversionStrategy
        from engine.backtest.strategies.momentum import MomentumStrategy
        from engine.backtest.strategies.rsi_reversion import RSIReversionStrategy
        from engine.backtest.strategies.trend_following import TrendFollowingStrategy
        from engine.backtest.strategies.volatility import VolatilityFilterStrategy

        _STRATEGY_REGISTRY = {
            "momentum": MomentumStrategy,
            "ma_crossover": MACrossoverStrategy,
            "rsi_reversion": RSIReversionStrategy,
            "breakout": BreakoutStrategy,
            "mean_reversion": MeanReversionStrategy,
            "trend_following": TrendFollowingStrategy,
            "volatility": VolatilityFilterStrategy,
            "combined": CombinedStrategy,
        }
    return _STRATEGY_REGISTRY


def make_strategy(name: str, params: dict[str, Any]) -> Strategy:
    """Instantiate a named strategy with the supplied params.

    Parameters
    ----------
    name:
        One of the registered strategy names (e.g. ``"momentum"``).
    params:
        Dict of keyword arguments forwarded to the strategy constructor.
        Unknown keys (not in the strategy's dataclass fields) raise
        ``ValueError``.

    Returns
    -------
    Strategy
        A frozen strategy instance.

    Raises
    ------
    ValueError
        If *name* is not registered or *params* contains unknown field names.
    """
    registry = _get_registry()
    cls = registry.get(name)
    if cls is None:
        valid = ", ".join(sorted(registry))
        raise ValueError(f"Unknown strategy {name!r}. Valid names: {valid}")

    # Validate params against the dataclass fields
    known_fields: set[str] = {f.name for f in dataclasses.fields(cls)}
    for key in params:
        if key not in known_fields:
            raise ValueError(f"Strategy {name!r} has no parameter {key!r}. Valid fields: {', '.join(sorted(known_fields))}")

    return cls(**params)


# ---------------------------------------------------------------------------
# Grid generation
# ---------------------------------------------------------------------------


def _combo_seed(base_seed: int, strategy: str, combo: dict[str, Any]) -> int:
    """Derive a deterministic seed from the strategy name and param values.

    This ensures the bootstrap RNG stream is tied to the *identity* of the
    combo, not its iteration order — so reordering ``--param`` flags or
    grid declarations produces identical results.
    """
    key = f"{base_seed}:{strategy}:" + ";".join(f"{k}={v}" for k, v in sorted(combo.items()))
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)


def _expand_grid(params: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """Expand a dict of param->values into all combinations."""
    if not params:
        return [{}]
    keys = list(params.keys())
    value_lists = [params[k] for k in keys]
    combos: list[dict[str, Any]] = []
    for values in itertools.product(*value_lists):
        combos.append(dict(zip(keys, values, strict=True)))
    return combos


# ---------------------------------------------------------------------------
# Sweep engine
# ---------------------------------------------------------------------------


def run_grid_sweep(
    *,
    config: GridConfig,
    close: np.ndarray,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    volume: np.ndarray | None = None,
    train_size: int,
    test_size: int,
    step_size: int,
    embargo: int = 0,
    backtest_cfg: BacktestConfig | None = None,
    n_boot: int = 2000,
    seed: int = 0,
    q: float = 0.05,
) -> SweepResult:
    """Run a full parameter grid sweep with FDR correction across all combos.

    For each parameter combination the function:

    1. Instantiates the strategy.
    2. Runs ``run_walkforward`` to get OOS returns.
    3. Applies ``bootstrap_p_value_mean_gt_zero`` to the combined OOS series.

    After all combos are evaluated, ``benjamini_hochberg`` is applied to the
    *full list* of p-values so that multiple-testing inflation is controlled.

    Parameters
    ----------
    config:
        Grid specification (strategy name + parameter grid).
    close, high, low, volume:
        Price arrays.
    train_size, test_size, step_size, embargo:
        Walk-forward window parameters.
    backtest_cfg:
        Passed to ``run_walkforward``; controls fee assumptions, etc.
    n_boot:
        Bootstrap resamples for the p-value calculation.
    seed:
        RNG seed for reproducibility.
    q:
        FDR threshold for Benjamini–Hochberg.

    Returns
    -------
    SweepResult
    """
    combos = _expand_grid(config.params)

    # --- validate params against the strategy before running anything ---
    registry = _get_registry()
    cls = registry.get(config.strategy)
    if cls is None:
        valid = ", ".join(sorted(registry))
        raise ValueError(f"Unknown strategy {config.strategy!r}. Valid names: {valid}")

    known_fields: set[str] = {f.name for f in dataclasses.fields(cls)}
    for combo in combos:
        for key in combo:
            if key not in known_fields:
                raise ValueError(f"Strategy {config.strategy!r} has no parameter {key!r}. Valid fields: {', '.join(sorted(known_fields))}")

    # --- per-combo evaluation ---
    partial_results: list[dict[str, Any]] = []
    p_values: list[float] = []

    for combo in combos:
        strat = make_strategy(config.strategy, combo)
        wf = run_walkforward(
            strategy=strat,
            close=close,
            high=high,
            low=low,
            volume=volume,
            train_size=train_size,
            test_size=test_size,
            step_size=step_size,
            embargo=embargo,
            cfg=backtest_cfg,
        )

        # Aggregate OOS metrics
        oos_returns = wf.combined_oos_returns
        oos_equity = wf.combined_oos_equity

        oos_total_return = float(oos_equity[-1] - 1.0) if oos_equity.size else 0.0

        # Sharpe from window metrics (mean across windows)
        if wf.window_metrics:
            oos_sharpe = float(np.mean([m["sharpe"] for m in wf.window_metrics]))
            oos_max_drawdown = float(np.mean([m["max_drawdown"] for m in wf.window_metrics]))
        else:
            oos_sharpe = 0.0
            oos_max_drawdown = 0.0

        combo_rng_seed = _combo_seed(seed, config.strategy, combo)
        test_result = bootstrap_p_value_mean_gt_zero(oos_returns, n_boot=n_boot, seed=combo_rng_seed)
        p_values.append(test_result.p_value)

        partial_results.append(
            {
                "strategy": config.strategy,
                "params": combo,
                "oos_total_return": oos_total_return,
                "oos_sharpe": oos_sharpe,
                "oos_max_drawdown": oos_max_drawdown,
                "mean_return": test_result.statistic,
                "p_value": test_result.p_value,
            }
        )

    # --- FDR correction across ALL combos ---
    fdr_mask = benjamini_hochberg(p_values, q=q)

    items: list[GridResult] = []
    for pr, fdr_pass in zip(partial_results, fdr_mask, strict=True):
        items.append(
            GridResult(
                strategy=pr["strategy"],
                params=pr["params"],
                oos_total_return=pr["oos_total_return"],
                oos_sharpe=pr["oos_sharpe"],
                oos_max_drawdown=pr["oos_max_drawdown"],
                mean_return=pr["mean_return"],
                p_value=pr["p_value"],
                bh_fdr_pass=bool(fdr_pass),
            )
        )

    fdr_survivors = sum(1 for it in items if it.bh_fdr_pass)

    return SweepResult(
        items=items,
        total_configs=len(items),
        fdr_survivors=fdr_survivors,
        q=q,
    )


# ---------------------------------------------------------------------------
# Default parameter grids per strategy
# ---------------------------------------------------------------------------

DEFAULT_GRIDS: dict[str, dict[str, list[Any]]] = {
    "momentum": {
        "lookback": [10, 20, 30, 50],
        "threshold": [0.01, 0.02, 0.05],
    },
    "ma_crossover": {
        "fast": [5, 10, 20],
        "slow": [50, 100, 200],
    },
    "rsi_reversion": {
        "period": [7, 14, 21],
        "oversold": [20.0, 30.0],
        "exit": [45.0, 50.0],
    },
    "breakout": {
        "lookback": [10, 20, 30, 50],
    },
    "mean_reversion": {
        "lookback": [10, 20, 30],
        "entry_z": [1.0, 1.5, 2.0],
        "exit_z": [0.0, 0.2, 0.5],
    },
    "trend_following": {
        "lookback": [20, 50, 100, 200],
    },
    "volatility": {
        "lookback": [10, 20, 30],
        "max_vol": [0.02, 0.03, 0.05],
    },
    "combined": {
        "mom_lookback": [10, 20, 30],
        "mom_threshold": [0.01, 0.02, 0.05],
        "fast": [5, 10],
        "slow": [50, 100],
    },
}


def get_default_configs() -> list[GridConfig]:
    """Return a list of GridConfig using default parameter grids for all strategies."""
    return [GridConfig(strategy=name, params=grid) for name, grid in DEFAULT_GRIDS.items()]


# ---------------------------------------------------------------------------
# Multi-strategy mega sweep
# ---------------------------------------------------------------------------


def run_multi_sweep(
    *,
    configs: list[GridConfig],
    close: np.ndarray,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    volume: np.ndarray | None = None,
    train_size: int,
    test_size: int,
    step_size: int,
    embargo: int = 0,
    backtest_cfg: BacktestConfig | None = None,
    n_boot: int = 2000,
    seed: int = 0,
    q: float = 0.05,
) -> MultiSweepResult:
    """Run multiple strategy grids and apply FDR across the ENTIRE universe.

    This is the real deal: sweeping 8 strategies × N param combos each gives
    hundreds of tests.  Applying BH-FDR once across all of them means anything
    that survives has genuine edge, not p-hacking luck.

    Parameters
    ----------
    configs:
        List of GridConfig, one per strategy (or per strategy variant).
    close, high, low, volume:
        Price arrays.
    train_size, test_size, step_size, embargo:
        Walk-forward window parameters.
    backtest_cfg:
        Fee assumptions, etc.
    n_boot:
        Bootstrap resamples.
    seed:
        RNG seed.
    q:
        FDR threshold for BH.

    Returns
    -------
    MultiSweepResult
    """
    all_partial: list[dict[str, Any]] = []
    all_p_values: list[float] = []
    strategies_seen: list[str] = []

    for config in configs:
        if config.strategy not in strategies_seen:
            strategies_seen.append(config.strategy)

        combos = _expand_grid(config.params)

        # Validate strategy + params
        registry = _get_registry()
        cls = registry.get(config.strategy)
        if cls is None:
            valid = ", ".join(sorted(registry))
            raise ValueError(f"Unknown strategy {config.strategy!r}. Valid names: {valid}")

        known_fields: set[str] = {f.name for f in dataclasses.fields(cls)}
        for combo in combos:
            for key in combo:
                if key not in known_fields:
                    raise ValueError(f"Strategy {config.strategy!r} has no parameter {key!r}. Valid fields: {', '.join(sorted(known_fields))}")

        for combo in combos:
            strat = make_strategy(config.strategy, combo)
            wf = run_walkforward(
                strategy=strat,
                close=close,
                high=high,
                low=low,
                volume=volume,
                train_size=train_size,
                test_size=test_size,
                step_size=step_size,
                embargo=embargo,
                cfg=backtest_cfg,
            )

            oos_returns = wf.combined_oos_returns
            oos_equity = wf.combined_oos_equity
            oos_total_return = float(oos_equity[-1] - 1.0) if oos_equity.size else 0.0

            if wf.window_metrics:
                oos_sharpe = float(np.mean([m["sharpe"] for m in wf.window_metrics]))
                oos_max_drawdown = float(np.mean([m["max_drawdown"] for m in wf.window_metrics]))
            else:
                oos_sharpe = 0.0
                oos_max_drawdown = 0.0

            combo_rng_seed = _combo_seed(seed, config.strategy, combo)
            test_result = bootstrap_p_value_mean_gt_zero(oos_returns, n_boot=n_boot, seed=combo_rng_seed)
            all_p_values.append(test_result.p_value)
            all_partial.append(
                {
                    "strategy": config.strategy,
                    "params": combo,
                    "oos_total_return": oos_total_return,
                    "oos_sharpe": oos_sharpe,
                    "oos_max_drawdown": oos_max_drawdown,
                    "mean_return": test_result.statistic,
                    "p_value": test_result.p_value,
                }
            )

    # --- FDR correction across ALL strategies × ALL combos ---
    fdr_mask = benjamini_hochberg(all_p_values, q=q)

    items: list[GridResult] = []
    for pr, fdr_pass in zip(all_partial, fdr_mask, strict=True):
        items.append(
            GridResult(
                strategy=pr["strategy"],
                params=pr["params"],
                oos_total_return=pr["oos_total_return"],
                oos_sharpe=pr["oos_sharpe"],
                oos_max_drawdown=pr["oos_max_drawdown"],
                mean_return=pr["mean_return"],
                p_value=pr["p_value"],
                bh_fdr_pass=bool(fdr_pass),
            )
        )

    fdr_survivors = sum(1 for it in items if it.bh_fdr_pass)

    return MultiSweepResult(
        items=items,
        total_configs=len(items),
        fdr_survivors=fdr_survivors,
        q=q,
        strategies_tested=strategies_seen,
    )
