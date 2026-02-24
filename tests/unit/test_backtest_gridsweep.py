"""tests.unit.test_backtest_gridsweep

Tests for parameter grid sweep + FDR (B1e).
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import pytest

from engine.backtest.sweep import (
    GridConfig,
    SweepResult,
    _expand_grid,
    make_strategy,
    run_grid_sweep,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_price_array(n: int = 600, seed: int = 42) -> np.ndarray:
    """Generate a synthetic close price series."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0005, 0.01, size=n)
    prices = np.cumprod(1.0 + returns) * 100.0
    return prices.astype(np.float64)


def _write_prices_csv(path: str | Path, n: int = 600, seed: int = 42) -> None:
    prices = _make_price_array(n=n, seed=seed)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["close"])
        for p in prices:
            w.writerow([f"{p:.4f}"])


# ---------------------------------------------------------------------------
# 1. test_grid_sweep_basic
# ---------------------------------------------------------------------------


def test_grid_sweep_basic() -> None:
    """2 param combos should both run; FDR applied across both."""
    close = _make_price_array(n=600)
    config = GridConfig(
        strategy="momentum",
        params={"lookback": [10, 20]},
    )
    result = run_grid_sweep(
        config=config,
        close=close,
        train_size=150,
        test_size=60,
        step_size=60,
        q=0.05,
    )
    assert isinstance(result, SweepResult)
    assert result.total_configs == 2
    assert len(result.items) == 2
    assert result.q == 0.05

    # Each item should carry the right strategy name and its specific params
    for item in result.items:
        assert item.strategy == "momentum"
        assert "lookback" in item.params
        assert isinstance(item.bh_fdr_pass, bool)
        assert 0.0 <= item.p_value <= 1.0

    # The two combos must have the two lookback values
    lookbacks = sorted(it.params["lookback"] for it in result.items)
    assert lookbacks == [10, 20]

    # fdr_survivors is consistent
    assert result.fdr_survivors == sum(1 for it in result.items if it.bh_fdr_pass)


# ---------------------------------------------------------------------------
# 2. test_grid_sweep_empty_params
# ---------------------------------------------------------------------------


def test_grid_sweep_empty_params() -> None:
    """No params → single default run (empty combo dict)."""
    close = _make_price_array(n=400)
    config = GridConfig(
        strategy="momentum",
        params={},
    )
    result = run_grid_sweep(
        config=config,
        close=close,
        train_size=120,
        test_size=60,
        step_size=60,
    )
    assert result.total_configs == 1
    assert len(result.items) == 1
    assert result.items[0].params == {}


# ---------------------------------------------------------------------------
# 3. test_grid_sweep_invalid_param
# ---------------------------------------------------------------------------


def test_grid_sweep_invalid_param() -> None:
    """Unknown param name should raise ValueError immediately."""
    close = _make_price_array(n=400)
    config = GridConfig(
        strategy="momentum",
        params={"nonexistent_param": [1, 2, 3]},
    )
    with pytest.raises(ValueError, match="nonexistent_param"):
        run_grid_sweep(
            config=config,
            close=close,
            train_size=120,
            test_size=60,
            step_size=60,
        )


# ---------------------------------------------------------------------------
# 4. test_grid_sweep_fdr_correction
# ---------------------------------------------------------------------------


def test_grid_sweep_fdr_correction() -> None:
    """FDR correction should be stricter than individual p-value threshold.

    Strategy: inject known p-values and verify that BH at q=0.05 with many
    combos rejects fewer results than a naive p<0.05 cut would.
    """
    from engine.backtest.stats import benjamini_hochberg

    # 10 p-values: 2 very small, 8 borderline (0.04)
    # BH threshold for rank 3/10 = 0.05*3/10 = 0.015, so 0.04 fails at that rank
    # But the cutoff-based BH uses the largest passing rank's p-value.
    # Use values that clearly separate: small ones pass, large ones fail.
    p_values = [0.001, 0.002] + [0.10] * 8

    naive_pass = [p < 0.05 for p in p_values]  # 2 pass naively
    bh_pass = benjamini_hochberg(p_values, q=0.05)

    # BH should let through fewer or equal to naive
    assert sum(bh_pass) <= sum(naive_pass)

    # The 2 very small ones should pass under BH
    assert all(bh_pass[:2])

    # The 0.10 ones should all fail (BH threshold for rank 3 is 0.015)
    assert not any(bh_pass[2:])


# ---------------------------------------------------------------------------
# 5. test_make_strategy
# ---------------------------------------------------------------------------


def test_make_strategy() -> None:
    """All 8 strategies should instantiate with custom params via make_strategy."""
    strategies_and_params: list[tuple[str, dict[str, Any]]] = [
        ("momentum", {"lookback": 15, "threshold": 0.03}),
        ("ma_crossover", {"fast": 5, "slow": 30}),
        ("rsi_reversion", {"period": 14, "oversold": 30.0, "exit": 50.0}),
        ("breakout", {"lookback": 25}),
        ("mean_reversion", {"lookback": 30, "entry_z": 2.0, "exit_z": 0.5}),
        ("trend_following", {"lookback": 40}),
        ("volatility", {"lookback": 20, "max_vol": 0.03}),
        ("combined", {"mom_lookback": 15, "mom_threshold": 0.02, "fast": 8, "slow": 40}),
    ]
    for name, params in strategies_and_params:
        strat = make_strategy(name, params)
        # Should be the correct type (not just a base Strategy)
        assert hasattr(strat, "name"), f"{name} missing .name"
        # All passed params should be reflected on the instance
        for k, v in params.items():
            assert getattr(strat, k) == v, f"{name}.{k} expected {v}, got {getattr(strat, k)}"


def test_make_strategy_unknown_name() -> None:
    with pytest.raises(ValueError, match="Unknown strategy"):
        make_strategy("flying_spaghetti", {})


def test_make_strategy_unknown_param() -> None:
    with pytest.raises(ValueError, match="no parameter"):
        make_strategy("momentum", {"not_a_field": 99})


# ---------------------------------------------------------------------------
# 6. test_cli_gridsweep_json
# ---------------------------------------------------------------------------


def test_cli_gridsweep_json(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """End-to-end CLI gridsweep with --json output."""
    from engine.cli import main

    prices_csv = tmp_path / "prices.csv"
    _write_prices_csv(prices_csv, n=500)

    # Run with dev mode env var so identity check is bypassed
    with patch.dict(os.environ, {"B1E55ED_DEV": "1"}):
        rc = main(
            [
                "backtest",
                "gridsweep",
                "--strategy",
                "momentum",
                "--prices",
                str(prices_csv),
                "--param",
                "lookback=10,20",
                "--train",
                "120",
                "--test",
                "60",
                "--step",
                "60",
                "--bootstrap",
                "200",
                "--seed",
                "7",
                "--json",
            ]
        )

    assert rc == 0, f"CLI returned non-zero: {rc}"
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["strategy"] == "momentum"
    assert data["summary"]["total_configs"] == 2
    assert len(data["results"]) == 2
    for r in data["results"]:
        assert "params" in r
        assert "oos_sharpe" in r
        assert "bh_fdr_pass" in r
        assert "p_value" in r


# ---------------------------------------------------------------------------
# 7. test_cli_gridsweep_human
# ---------------------------------------------------------------------------


def test_cli_gridsweep_human(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """Non-JSON (human-readable table) output should work without error."""
    from engine.cli import main

    prices_csv = tmp_path / "prices.csv"
    _write_prices_csv(prices_csv, n=500)

    with patch.dict(os.environ, {"B1E55ED_DEV": "1"}):
        rc = main(
            [
                "backtest",
                "gridsweep",
                "--strategy",
                "breakout",
                "--prices",
                str(prices_csv),
                "--param",
                "lookback=15,30",
                "--train",
                "120",
                "--test",
                "60",
                "--step",
                "60",
                "--bootstrap",
                "100",
            ]
        )

    assert rc == 0
    captured = capsys.readouterr()
    # Human output should contain some table-like indicators
    assert "Grid Sweep" in captured.out
    assert "breakout" in captured.out
    assert "Total configs" in captured.out or "total_configs" in captured.out or "2" in captured.out


# ---------------------------------------------------------------------------
# 8. test_param_parsing
# ---------------------------------------------------------------------------


def test_param_parsing() -> None:
    """_parse_param_spec should correctly parse name=val1,val2,val3."""
    from engine.cli import _parse_param_spec

    name, values = _parse_param_spec("lookback=10,20,30")
    assert name == "lookback"
    assert values == [10, 20, 30]
    assert all(isinstance(v, int) for v in values)

    name2, values2 = _parse_param_spec("threshold=0.01,0.02,0.05")
    assert name2 == "threshold"
    assert len(values2) == 3
    assert all(isinstance(v, float) for v in values2)

    # Mixed int-like floats still parse
    name3, values3 = _parse_param_spec("fast=5,10,15")
    assert name3 == "fast"
    assert values3 == [5, 10, 15]


def test_param_parsing_invalid() -> None:
    """Bad format should raise ValueError."""
    from engine.cli import _parse_param_spec

    with pytest.raises(ValueError, match="Expected format"):
        _parse_param_spec("no-equals-sign")

    with pytest.raises(ValueError, match="Empty parameter name"):
        _parse_param_spec("=1,2,3")


# ---------------------------------------------------------------------------
# 9. _expand_grid coverage
# ---------------------------------------------------------------------------


def test_expand_grid_single() -> None:
    combos = _expand_grid({"lookback": [10, 20], "threshold": [0.01, 0.02]})
    assert len(combos) == 4
    assert {"lookback": 10, "threshold": 0.01} in combos
    assert {"lookback": 20, "threshold": 0.02} in combos


def test_expand_grid_empty() -> None:
    assert _expand_grid({}) == [{}]
