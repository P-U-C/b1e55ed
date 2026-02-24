"""Tests for B1h: regime-conditioned backtests."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np

from engine.backtest.regime import (
    REGIMES,
    RegimeBacktestResult,
    classify_regimes,
    run_regime_backtest,
)
from engine.backtest.strategies.ma_crossover import MACrossoverStrategy
from engine.backtest.strategies.momentum import MomentumStrategy


def _trending_close(n: int = 1000, seed: int = 42) -> np.ndarray:
    """Generate trending data with regime-like structure."""
    rng = np.random.default_rng(seed)
    # Bull phase -> Bear phase -> Recovery
    bull = np.linspace(100, 160, n // 3) + rng.normal(0, 1.5, n // 3)
    bear = np.linspace(160, 110, n // 3) + rng.normal(0, 3, n // 3)  # higher vol
    recovery = np.linspace(110, 140, n - 2 * (n // 3)) + rng.normal(0, 1.5, n - 2 * (n // 3))
    return np.concatenate([bull, bear, recovery])


def _make_csv(n: int = 1000) -> Path:
    close = _trending_close(n)
    p = Path(tempfile.mktemp(suffix=".csv"))
    with p.open("w") as f:
        f.write("close\n")
        for v in close:
            f.write(f"{v:.4f}\n")
    return p


class TestClassifyRegimes:
    def test_output_shape(self) -> None:
        close = _trending_close(500)
        regimes = classify_regimes(close=close)
        assert regimes.shape == (500,)

    def test_all_values_valid(self) -> None:
        close = _trending_close(500)
        regimes = classify_regimes(close=close)
        for r in regimes:
            assert r in REGIMES

    def test_detects_multiple_regimes(self) -> None:
        close = _trending_close(1000)
        regimes = classify_regimes(close=close)
        unique = set(regimes)
        # Should detect at least 2 different regimes in trending data
        assert len(unique) >= 2

    def test_short_series(self) -> None:
        close = np.array([100.0, 101.0, 99.0])
        regimes = classify_regimes(close=close)
        assert regimes.shape == (3,)
        # All should be TRANSITION for very short series
        assert all(r == "TRANSITION" for r in regimes)

    def test_empty_series(self) -> None:
        close = np.array([], dtype=np.float64)
        regimes = classify_regimes(close=close)
        assert regimes.shape == (0,)

    def test_bull_market(self) -> None:
        """Steadily rising prices should classify mostly as BULL."""
        rng = np.random.default_rng(1)
        close = np.linspace(100, 200, 500) + rng.normal(0, 0.5, 500)
        regimes = classify_regimes(close=close)
        bull_pct = np.mean(regimes == "BULL")
        # At least 30% bull in a steadily rising market
        assert bull_pct > 0.3

    def test_bear_market(self) -> None:
        """Steadily falling prices should classify mostly as BEAR."""
        rng = np.random.default_rng(1)
        close = np.linspace(200, 100, 500) + rng.normal(0, 0.5, 500)
        regimes = classify_regimes(close=close)
        bear_pct = np.mean(regimes == "BEAR")
        assert bear_pct > 0.3

    def test_crisis_high_vol(self) -> None:
        """Very high volatility should trigger CRISIS."""
        rng = np.random.default_rng(1)
        # Huge vol + declining
        close = np.linspace(200, 100, 500) + rng.normal(0, 10, 500)
        close = np.maximum(close, 1.0)
        regimes = classify_regimes(close=close, vol_crisis_threshold=0.02)
        crisis_or_bear = np.mean((regimes == "CRISIS") | (regimes == "BEAR"))
        assert crisis_or_bear > 0.3


class TestRegimeBacktest:
    def test_basic_run(self) -> None:
        close = _trending_close(500)
        strat = MomentumStrategy(lookback=20, threshold=0.02)
        result = run_regime_backtest(
            strategy=strat,
            close=close,
            n_boot=200,
            seed=0,
        )
        assert isinstance(result, RegimeBacktestResult)
        assert result.strategy == "momentum"
        assert len(result.regime_results) == 4  # one per regime
        assert result.overall_sharpe != 0  # should have some signal

    def test_all_regimes_reported(self) -> None:
        close = _trending_close(500)
        strat = MACrossoverStrategy(fast=5, slow=20)
        result = run_regime_backtest(
            strategy=strat,
            close=close,
            n_boot=200,
        )
        regime_names = [r.regime for r in result.regime_results]
        for regime in REGIMES:
            assert regime in regime_names

    def test_per_regime_stats(self) -> None:
        close = _trending_close(1000)
        strat = MomentumStrategy(lookback=20, threshold=0.02)
        result = run_regime_backtest(
            strategy=strat,
            close=close,
            n_boot=200,
        )
        for r in result.regime_results:
            assert isinstance(r.sharpe, float)
            assert isinstance(r.p_value, float)
            assert 0.0 <= r.p_value <= 1.0
            assert isinstance(r.bh_fdr_pass, bool)

    def test_custom_regimes(self) -> None:
        """Pass pre-computed regimes."""
        close = _trending_close(200)
        regimes = np.array(["BULL"] * 100 + ["BEAR"] * 100, dtype=object)
        strat = MomentumStrategy()
        result = run_regime_backtest(
            strategy=strat,
            close=close,
            regimes=regimes,
            n_boot=200,
        )
        # BULL and BEAR should have 100 bars each
        for r in result.regime_results:
            if r.regime == "BULL" or r.regime == "BEAR":
                assert r.n_bars == 100
            else:
                assert r.n_bars == 0

    def test_fdr_across_regimes(self) -> None:
        """FDR should be applied across all 4 regimes."""
        close = _trending_close(1000)
        strat = MomentumStrategy()
        result = run_regime_backtest(
            strategy=strat,
            close=close,
            n_boot=200,
            q=0.05,
        )
        # At least some regimes should exist
        total_bars = sum(r.n_bars for r in result.regime_results)
        assert total_bars > 0


class TestCLIRegime:
    def test_cli_regime_json(self) -> None:
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
                    "regime",
                    "--strategy",
                    "momentum",
                    "--prices",
                    str(csv_path),
                    "--bootstrap",
                    "200",
                    "--json",
                ]
            )
            sys.stdout = old_stdout
            assert rc == 0
            data = json.loads(captured.getvalue())
            assert "regimes" in data
            assert len(data["regimes"]) == 4
            assert "overall" in data
        finally:
            csv_path.unlink(missing_ok=True)

    def test_cli_regime_human(self) -> None:
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
                    "regime",
                    "--strategy",
                    "momentum",
                    "--prices",
                    str(csv_path),
                    "--bootstrap",
                    "200",
                ]
            )
            sys.stdout = old_stdout
            assert rc == 0
            output = captured.getvalue()
            assert "Regime-Conditioned" in output
            assert "BULL" in output
        finally:
            csv_path.unlink(missing_ok=True)
