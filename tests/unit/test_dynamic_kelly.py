"""Tests for B1g: Dynamic Kelly criterion."""

from __future__ import annotations

import json

import pytest

from engine.core.database import Database
from engine.execution.dynamic_kelly import DynamicKelly, DynamicKellyConfig
from engine.execution.position_sizer import KellyParams


def _setup_db(tmp_path) -> Database:
    db = Database(str(tmp_path / "test.db"))
    return db


def _insert_trades(db: Database, trades: list[dict]) -> None:
    """Insert closed positions with realized PnL."""
    for i, t in enumerate(trades):
        db.conn.execute(
            """INSERT INTO positions (id, platform, asset, direction, entry_price,
               size_notional, opened_at, closed_at, status, realized_pnl)
               VALUES (?, 'test', ?, 'long', 100.0, 1000.0, '2026-01-01', ?, 'closed', ?)""",
            (f"pos_{i}", t.get("asset", "BTC"), f"2026-01-{i + 2:02d}", t["pnl"]),
        )
    db.conn.commit()


class TestDynamicKellyBasic:
    def test_no_trades_uses_prior(self, tmp_path) -> None:
        db = _setup_db(tmp_path)
        dk = DynamicKelly(db)
        est = dk.estimate()

        assert est.n_trades == 0
        assert est.used_prior is True
        assert est.p == pytest.approx(0.5, abs=0.01)
        assert est.b == pytest.approx(1.0, abs=0.01)

    def test_few_trades_blends_prior(self, tmp_path) -> None:
        db = _setup_db(tmp_path)
        # 5 trades: 4 wins, 1 loss (below min_trades=10)
        _insert_trades(
            db,
            [
                {"pnl": 100.0},
                {"pnl": 50.0},
                {"pnl": 80.0},
                {"pnl": 200.0},
                {"pnl": -60.0},
            ],
        )
        dk = DynamicKelly(db)
        est = dk.estimate()

        assert est.n_trades == 5
        assert est.used_prior is True
        # Should be blended: not pure 0.8 win rate
        assert 0.5 < est.p < 0.8
        assert est.b > 0

    def test_enough_trades_data_driven(self, tmp_path) -> None:
        db = _setup_db(tmp_path)
        # 15 trades: 10 wins, 5 losses
        trades = [{"pnl": 100.0}] * 10 + [{"pnl": -80.0}] * 5
        _insert_trades(db, trades)
        dk = DynamicKelly(db)
        est = dk.estimate()

        assert est.n_trades == 15
        assert est.used_prior is False
        assert est.n_wins == 10
        assert est.n_losses == 5
        # With decay, p won't be exactly 10/15 but should be close
        assert 0.5 < est.p < 0.8

    def test_all_wins(self, tmp_path) -> None:
        db = _setup_db(tmp_path)
        trades = [{"pnl": 50.0}] * 12
        _insert_trades(db, trades)
        dk = DynamicKelly(db, config=DynamicKellyConfig(decay_halflife=None))
        est = dk.estimate()

        assert est.p == pytest.approx(1.0, abs=0.01)
        assert est.n_wins == 12
        assert est.n_losses == 0

    def test_all_losses(self, tmp_path) -> None:
        db = _setup_db(tmp_path)
        trades = [{"pnl": -50.0}] * 12
        _insert_trades(db, trades)
        dk = DynamicKelly(db, config=DynamicKellyConfig(decay_halflife=None))
        est = dk.estimate()

        assert est.p == pytest.approx(0.0, abs=0.01)
        assert est.kelly_fraction == 0.0  # below min_p_for_betting

    def test_kelly_fraction_calculation(self, tmp_path) -> None:
        db = _setup_db(tmp_path)
        # 60% win rate, avg win $100, avg loss $80, b = 1.25
        trades = [{"pnl": 100.0}] * 12 + [{"pnl": -80.0}] * 8
        _insert_trades(db, trades)
        dk = DynamicKelly(db, config=DynamicKellyConfig(decay_halflife=None))
        est = dk.estimate()

        # Kelly = (b*p - q) / b = (1.25*0.6 - 0.4) / 1.25 = 0.28
        assert est.kelly_fraction > 0
        assert est.params.fraction_multiplier == 0.5  # half-Kelly

    def test_returns_kelly_params(self, tmp_path) -> None:
        db = _setup_db(tmp_path)
        trades = [{"pnl": 100.0}] * 10 + [{"pnl": -80.0}] * 5
        _insert_trades(db, trades)
        dk = DynamicKelly(db)
        params = dk.compute()

        assert isinstance(params, KellyParams)
        assert params.p > 0
        assert params.b > 0
        assert params.fraction_multiplier == 0.5


class TestDynamicKellyFiltering:
    def test_filter_by_asset(self, tmp_path) -> None:
        db = _setup_db(tmp_path)
        _insert_trades(
            db,
            [
                {"pnl": 100.0, "asset": "BTC"},
                {"pnl": 100.0, "asset": "BTC"},
                {"pnl": -50.0, "asset": "ETH"},
                {"pnl": -50.0, "asset": "ETH"},
            ],
        )
        dk = DynamicKelly(db)

        btc_est = dk.estimate(asset="BTC")
        assert btc_est.n_trades == 2
        assert btc_est.n_wins == 2

        eth_est = dk.estimate(asset="ETH")
        assert eth_est.n_trades == 2
        assert eth_est.n_losses == 2

    def test_lookback_limit(self, tmp_path) -> None:
        db = _setup_db(tmp_path)
        trades = [{"pnl": 100.0}] * 30
        _insert_trades(db, trades)

        dk = DynamicKelly(db, config=DynamicKellyConfig(lookback=10, min_trades=5, decay_halflife=None))
        est = dk.estimate()
        assert est.n_trades == 10


class TestFlatTradesInPrior:
    def test_flat_trades_counted_in_denominator(self, tmp_path) -> None:
        """Flat trades (pnl=0) must count toward n_trades denominator in prior blend."""
        db = _setup_db(tmp_path)
        # 2 wins + 2 flat + 1 loss = 5 trades total, but n_wins+n_losses = 3
        # With flat trades dropped: p = (prior*pw + 2) / (pw + 3)
        # With flat trades included: p = (prior*pw + 2) / (pw + 5)  ← correct
        _insert_trades(
            db,
            [
                {"pnl": 100.0},
                {"pnl": 50.0},  # 2 wins
                {"pnl": 0.0},
                {"pnl": 0.0},  # 2 flat (scratch)
                {"pnl": -30.0},  # 1 loss
            ],
        )
        dk_flat = DynamicKelly(db, config=DynamicKellyConfig(prior_weight=5))
        est = dk_flat.estimate()

        assert est.n_trades == 5
        assert est.n_wins == 2
        assert est.n_losses == 1
        # p should be blended using denominator=5 (not 3)
        prior_p, pw = 0.50, 5
        expected_p = (prior_p * pw + 2) / (pw + 5)
        assert est.p == pytest.approx(expected_p, abs=0.01)


class TestDecayWeighting:
    def test_b_is_conditional_not_unconditional(self, tmp_path) -> None:
        """b = avg_win / avg_loss must use conditional means, not contaminate with win rate."""
        db = _setup_db(tmp_path)
        # 70% win rate, avg_win=$100, avg_loss=$50 → b should = 2.0, not 4.67
        trades = [{"pnl": 100.0}] * 7 + [{"pnl": -50.0}] * 3
        _insert_trades(db, trades)
        dk = DynamicKelly(db, config=DynamicKellyConfig(decay_halflife=5, min_trades=5))
        est = dk.estimate()
        # b should be close to 2.0 regardless of win rate
        assert est.b == pytest.approx(2.0, abs=0.1)

    def test_recent_trades_matter_more(self, tmp_path) -> None:
        db = _setup_db(tmp_path)
        # Old trades: all losses. Recent trades: all wins.
        trades = [{"pnl": -100.0}] * 10 + [{"pnl": 100.0}] * 10
        _insert_trades(db, trades)

        # With decay, p should be > 0.5 (recent wins weighted higher)
        dk_decay = DynamicKelly(db, config=DynamicKellyConfig(min_trades=5, decay_halflife=5))
        est_decay = dk_decay.estimate()

        # Without decay, p = 0.5 exactly
        dk_nodecay = DynamicKelly(db, config=DynamicKellyConfig(min_trades=5, decay_halflife=None))
        est_nodecay = dk_nodecay.estimate()

        assert est_decay.p > est_nodecay.p


class TestBayesianPrior:
    def test_prior_weight_effect(self, tmp_path) -> None:
        db = _setup_db(tmp_path)
        # 3 trades, all wins — below min_trades
        _insert_trades(db, [{"pnl": 100.0}] * 3)

        # Heavy prior (weight=20): should pull p toward 0.5
        dk_heavy = DynamicKelly(db, config=DynamicKellyConfig(prior_weight=20))
        est_heavy = dk_heavy.estimate()

        # Light prior (weight=1): should be closer to 1.0
        dk_light = DynamicKelly(db, config=DynamicKellyConfig(prior_weight=1))
        est_light = dk_light.estimate()

        assert est_heavy.p < est_light.p
        assert est_heavy.used_prior is True
        assert est_light.used_prior is True


class TestMinPForBetting:
    def test_low_p_zeros_kelly(self, tmp_path) -> None:
        db = _setup_db(tmp_path)
        # 20% win rate
        trades = [{"pnl": 100.0}] * 4 + [{"pnl": -50.0}] * 16
        _insert_trades(db, trades)
        dk = DynamicKelly(db, config=DynamicKellyConfig(decay_halflife=None, min_p_for_betting=0.35))
        est = dk.estimate()

        assert est.p < 0.35
        assert est.kelly_fraction == 0.0

    def test_low_p_zeros_params_fraction_multiplier(self, tmp_path) -> None:
        """params.fraction_multiplier must be 0 when below floor — not just kelly_fraction."""
        db = _setup_db(tmp_path)
        trades = [{"pnl": 100.0}] * 4 + [{"pnl": -50.0}] * 16
        _insert_trades(db, trades)
        dk = DynamicKelly(db, config=DynamicKellyConfig(decay_halflife=None, min_p_for_betting=0.35))
        est = dk.estimate()

        # Any caller using compute() → PositionSizer(kelly=params) must also get 0
        assert est.params.fraction_multiplier == 0.0

        # Verify PositionSizer also gives 0
        from engine.execution.position_sizer import PositionSizer

        sizer = PositionSizer(kelly=est.params)
        assert sizer.kelly_fraction() == 0.0


def _setup_cli_db(tmp_path, monkeypatch) -> None:
    """Create brain.db at ~/.b1e55ed/data/ (the path used by CLI commands)."""
    home_dir = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home_dir))
    data_dir = home_dir / ".b1e55ed" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(str(data_dir / "brain.db"))
    _insert_trades(db, [{"pnl": 100.0}] * 8 + [{"pnl": -60.0}] * 4)
    db.close()


class TestCLIKelly:
    def test_cli_kelly_json(self, tmp_path, monkeypatch) -> None:
        from engine.cli import main

        _setup_cli_db(tmp_path, monkeypatch)
        monkeypatch.chdir(tmp_path)

        import io
        import sys

        captured = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured)

        rc = main(["kelly", "--json"])

        assert rc == 0
        data = json.loads(captured.getvalue())
        assert "p" in data
        assert "b" in data
        assert "n_trades" in data
        assert data["n_trades"] == 12

    def test_cli_kelly_human(self, tmp_path, monkeypatch) -> None:
        from engine.cli import main

        _setup_cli_db(tmp_path, monkeypatch)
        monkeypatch.chdir(tmp_path)

        import io
        import sys

        captured = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured)

        rc = main(["kelly"])

        assert rc == 0
        output = captured.getvalue()
        assert "Dynamic Kelly" in output
        assert "Win rate" in output
