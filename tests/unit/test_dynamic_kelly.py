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


class TestDecayWeighting:
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


class TestCLIKelly:
    def test_cli_kelly_json(self, tmp_path) -> None:
        from engine.cli import main

        db = Database(str(tmp_path / "brain.db"))
        _insert_trades(db, [{"pnl": 100.0}] * 8 + [{"pnl": -60.0}] * 4)
        db.close()

        import io
        import os
        import sys

        old_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            rc = main(["kelly", "--json"])
        finally:
            sys.stdout = old_stdout
            os.chdir(old_cwd)

        assert rc == 0
        data = json.loads(captured.getvalue())
        assert "p" in data
        assert "b" in data
        assert "n_trades" in data
        assert data["n_trades"] == 12

    def test_cli_kelly_human(self, tmp_path) -> None:
        from engine.cli import main

        db = Database(str(tmp_path / "brain.db"))
        _insert_trades(db, [{"pnl": 100.0}] * 8 + [{"pnl": -60.0}] * 4)
        db.close()

        import io
        import os
        import sys

        old_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            rc = main(["kelly"])
        finally:
            sys.stdout = old_stdout
            os.chdir(old_cwd)

        assert rc == 0
        output = captured.getvalue()
        assert "Dynamic Kelly" in output
        assert "Win rate" in output
