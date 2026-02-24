"""Tests for B1f: multi-strategy mega sweep."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pytest

from engine.backtest.sweep import (
    DEFAULT_GRIDS,
    GridConfig,
    MultiSweepResult,
    get_default_configs,
    run_multi_sweep,
)


def _make_csv(n: int = 500) -> Path:
    """Create a temp CSV with trending data so some strategies produce signal."""
    rng = np.random.default_rng(42)
    # trending + noise
    trend = np.linspace(100, 150, n) + rng.normal(0, 2, n)
    p = Path(tempfile.mktemp(suffix=".csv"))
    with p.open("w") as f:
        f.write("close\n")
        for v in trend:
            f.write(f"{v:.4f}\n")
    return p


def _random_close(n: int = 500, seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100.0 + np.cumsum(rng.normal(0.0002, 0.01, n))


class TestMultiSweep:
    def test_basic_two_strategies(self) -> None:
        close = _random_close(500)
        configs = [
            GridConfig(strategy="momentum", params={"lookback": [10, 20]}),
            GridConfig(strategy="breakout", params={"lookback": [10, 20]}),
        ]
        result = run_multi_sweep(
            configs=configs,
            close=close,
            train_size=100,
            test_size=50,
            step_size=50,
            n_boot=200,
            seed=0,
            q=0.05,
        )
        assert isinstance(result, MultiSweepResult)
        assert result.total_configs == 4  # 2 + 2
        assert len(result.items) == 4
        assert "momentum" in result.strategies_tested
        assert "breakout" in result.strategies_tested
        # FDR survivors <= total
        assert 0 <= result.fdr_survivors <= result.total_configs

    def test_fdr_across_all(self) -> None:
        """FDR should be stricter than per-strategy correction."""
        close = _random_close(500)
        # Run 3 strategies with small grids
        configs = [
            GridConfig(strategy="momentum", params={"lookback": [10, 20, 30]}),
            GridConfig(strategy="ma_crossover", params={"fast": [5, 10], "slow": [50]}),
            GridConfig(strategy="trend_following", params={"lookback": [20, 50]}),
        ]
        result = run_multi_sweep(
            configs=configs,
            close=close,
            train_size=100,
            test_size=50,
            step_size=50,
            n_boot=200,
            seed=0,
            q=0.05,
        )
        # 3 + 2 + 2 = 7 combos, FDR applied across all 7
        assert result.total_configs == 7
        assert len(result.items) == 7
        # Each item has the right fields
        for item in result.items:
            assert item.strategy in ("momentum", "ma_crossover", "trend_following")
            assert isinstance(item.p_value, float)
            assert isinstance(item.bh_fdr_pass, bool)

    def test_single_strategy_matches_gridsweep(self) -> None:
        """Single-strategy mega sweep should produce same results as gridsweep."""
        from engine.backtest.sweep import run_grid_sweep

        close = _random_close(500)
        config = GridConfig(strategy="momentum", params={"lookback": [10, 20]})

        grid_result = run_grid_sweep(
            config=config,
            close=close,
            train_size=100,
            test_size=50,
            step_size=50,
            n_boot=200,
            seed=0,
            q=0.05,
        )
        multi_result = run_multi_sweep(
            configs=[config],
            close=close,
            train_size=100,
            test_size=50,
            step_size=50,
            n_boot=200,
            seed=0,
            q=0.05,
        )

        assert grid_result.total_configs == multi_result.total_configs
        for g, m in zip(grid_result.items, multi_result.items, strict=True):
            assert g.strategy == m.strategy
            assert g.params == m.params
            assert abs(g.p_value - m.p_value) < 1e-10
            assert g.bh_fdr_pass == m.bh_fdr_pass

    def test_empty_configs_raises(self) -> None:
        close = _random_close(100)
        result = run_multi_sweep(
            configs=[],
            close=close,
            train_size=50,
            test_size=20,
            step_size=20,
        )
        assert result.total_configs == 0
        assert result.fdr_survivors == 0

    def test_invalid_strategy_raises(self) -> None:
        close = _random_close(100)
        with pytest.raises(ValueError, match="Unknown strategy"):
            run_multi_sweep(
                configs=[GridConfig(strategy="nonexistent", params={})],
                close=close,
                train_size=50,
                test_size=20,
                step_size=20,
            )

    def test_invalid_param_raises(self) -> None:
        close = _random_close(100)
        with pytest.raises(ValueError, match="has no parameter"):
            run_multi_sweep(
                configs=[GridConfig(strategy="momentum", params={"bad_param": [1, 2]})],
                close=close,
                train_size=50,
                test_size=20,
                step_size=20,
            )


class TestDefaultGrids:
    def test_all_strategies_have_defaults(self) -> None:
        from engine.backtest.sweep import _get_registry

        registry = _get_registry()
        for name in registry:
            assert name in DEFAULT_GRIDS, f"Strategy {name!r} has no default grid"

    def test_get_default_configs(self) -> None:
        configs = get_default_configs()
        assert len(configs) == 8
        names = [c.strategy for c in configs]
        assert "momentum" in names
        assert "combined" in names

    def test_default_grids_valid_params(self) -> None:
        """All default grid params must be valid fields on the strategy."""
        import dataclasses

        from engine.backtest.sweep import _get_registry

        registry = _get_registry()
        for name, grid in DEFAULT_GRIDS.items():
            cls = registry[name]
            known = {f.name for f in dataclasses.fields(cls)}
            for param in grid:
                assert param in known, f"Default grid for {name!r} has invalid param {param!r}"


class TestGridSpecParsing:
    def test_parse_grid_spec_basic(self) -> None:
        from engine.cli import _parse_grid_spec

        strategy, params = _parse_grid_spec("momentum:lookback=10,20;threshold=0.01,0.02")
        assert strategy == "momentum"
        assert params == {"lookback": [10, 20], "threshold": [0.01, 0.02]}

    def test_parse_grid_spec_no_params(self) -> None:
        from engine.cli import _parse_grid_spec

        strategy, params = _parse_grid_spec("momentum:")
        assert strategy == "momentum"
        assert params == {}

    def test_parse_grid_spec_no_colon(self) -> None:
        from engine.cli import _parse_grid_spec

        with pytest.raises(ValueError, match="Invalid --grid spec"):
            _parse_grid_spec("momentum")

    def test_parse_grid_spec_empty_strategy(self) -> None:
        from engine.cli import _parse_grid_spec

        with pytest.raises(ValueError, match="Empty strategy name"):
            _parse_grid_spec(":lookback=10,20")


class TestCLIMegasweep:
    def test_cli_megasweep_json(self) -> None:
        from engine.cli import main

        csv_path = _make_csv(500)
        try:
            import io
            import sys

            captured = io.StringIO()
            old_stdout = sys.stdout
            sys.stdout = captured
            rc = main(
                [
                    "backtest",
                    "megasweep",
                    "--prices",
                    str(csv_path),
                    "--grid",
                    "momentum:lookback=10,20",
                    "--grid",
                    "breakout:lookback=10,20",
                    "--train",
                    "100",
                    "--test",
                    "50",
                    "--step",
                    "50",
                    "--bootstrap",
                    "200",
                    "--json",
                ]
            )
            sys.stdout = old_stdout
            assert rc == 0
            output = captured.getvalue()
            data = json.loads(output)
            assert data["summary"]["total_configs"] == 4
            assert "results" in data
            assert len(data["results"]) == 4
        finally:
            csv_path.unlink(missing_ok=True)

    def test_cli_megasweep_human(self) -> None:
        from engine.cli import main

        csv_path = _make_csv(500)
        try:
            import io
            import sys

            captured = io.StringIO()
            old_stdout = sys.stdout
            sys.stdout = captured
            rc = main(
                [
                    "backtest",
                    "megasweep",
                    "--prices",
                    str(csv_path),
                    "--grid",
                    "momentum:lookback=10,20",
                    "--train",
                    "100",
                    "--test",
                    "50",
                    "--step",
                    "50",
                    "--bootstrap",
                    "200",
                ]
            )
            sys.stdout = old_stdout
            assert rc == 0
            output = captured.getvalue()
            assert "MEGA SWEEP" in output
            assert "momentum" in output
        finally:
            csv_path.unlink(missing_ok=True)

    def test_cli_megasweep_all_defaults(self) -> None:
        from engine.cli import main

        csv_path = _make_csv(500)
        try:
            import io
            import sys

            captured = io.StringIO()
            old_stdout = sys.stdout
            sys.stdout = captured
            rc = main(
                [
                    "backtest",
                    "megasweep",
                    "--prices",
                    str(csv_path),
                    "--all-defaults",
                    "--train",
                    "100",
                    "--test",
                    "50",
                    "--step",
                    "50",
                    "--bootstrap",
                    "100",
                    "--json",
                ]
            )
            sys.stdout = old_stdout
            assert rc == 0
            output = captured.getvalue()
            data = json.loads(output)
            assert data["summary"]["total_configs"] > 50  # 8 strategies × many combos
            assert len(data["summary"]["strategies_tested"]) == 8
        finally:
            csv_path.unlink(missing_ok=True)

    def test_cli_megasweep_no_args_fails(self) -> None:
        from engine.cli import main

        csv_path = _make_csv(100)
        try:
            rc = main(
                [
                    "backtest",
                    "megasweep",
                    "--prices",
                    str(csv_path),
                ]
            )
            assert rc == 2
        finally:
            csv_path.unlink(missing_ok=True)

    def test_cli_megasweep_both_flags_fails(self) -> None:
        from engine.cli import main

        csv_path = _make_csv(100)
        try:
            rc = main(
                [
                    "backtest",
                    "megasweep",
                    "--prices",
                    str(csv_path),
                    "--all-defaults",
                    "--grid",
                    "momentum:lookback=10",
                ]
            )
            assert rc == 2
        finally:
            csv_path.unlink(missing_ok=True)
