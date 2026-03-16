"""tests/test_engine_audit.py

Tests proving fixes for the engine audit (fix/engine-audit branch).

Bugs fixed:
1. regime_at_entry/pcs_at_entry not written by PaperBroker
2. Position deduplication: same symbol cannot get two open positions
3. signal_log table missing from schema
4. test_identity_show_with_no_identity using production identity (fixed in test_identity_cli.py)
5. Polymarket producer EV filter adds observability logging
6. TA producer silently handles non-crypto symbols (SPY/QQQ)
"""

from __future__ import annotations

import pytest

try:
    from datetime import UTC
except ImportError:

    UTC = UTC

from engine.core.database import Database
from engine.execution.paper import PaperBroker


@pytest.fixture
def db(tmp_path):
    d = Database(db_path=tmp_path / "test.db")
    yield d
    d.close()


# ─────────────────────────────────────────────────────────────────────────────
# Bug 1: regime_at_entry / pcs_at_entry written to positions table
# ─────────────────────────────────────────────────────────────────────────────


class TestRegimeAtEntryWritten:
    def test_regime_and_pcs_written(self, db):
        """PaperBroker.execute_market must persist regime_at_entry and pcs_at_entry."""
        broker = PaperBroker(db)
        fill = broker.execute_market(
            symbol="BTC",
            direction="long",
            notional_usd=500.0,
            mid_price=50_000.0,
            regime_at_entry="BULL",
            pcs_at_entry=72.5,
        )
        row = db.fetchone(
            "SELECT regime_at_entry, pcs_at_entry FROM positions WHERE id = ?",
            (fill.position_id,),
        )
        assert row is not None
        assert row["regime_at_entry"] == "BULL"
        assert abs(row["pcs_at_entry"] - 72.5) < 1e-6

    def test_none_values_accepted(self, db):
        """Null regime/pcs must not fail — they are optional."""
        broker = PaperBroker(db)
        fill = broker.execute_market(
            symbol="ETH",
            direction="short",
            notional_usd=200.0,
            mid_price=3_000.0,
            regime_at_entry=None,
            pcs_at_entry=None,
        )
        row = db.fetchone(
            "SELECT regime_at_entry, pcs_at_entry FROM positions WHERE id = ?",
            (fill.position_id,),
        )
        assert row is not None
        assert row["regime_at_entry"] is None
        assert row["pcs_at_entry"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Bug 2: Position deduplication — same symbol cannot have two open positions
# ─────────────────────────────────────────────────────────────────────────────


class TestPositionDeduplication:
    def test_second_open_rejected(self, db):
        """A second execute_market for the same symbol raises ValueError."""
        broker = PaperBroker(db)
        broker.execute_market(
            symbol="BTC",
            direction="long",
            notional_usd=500.0,
            mid_price=50_000.0,
        )
        with pytest.raises(ValueError, match="duplicate_open_position"):
            broker.execute_market(
                symbol="BTC",
                direction="long",
                notional_usd=300.0,
                mid_price=51_000.0,
            )

    def test_different_symbols_allowed(self, db):
        """Different symbols can each have one open position."""
        broker = PaperBroker(db)
        broker.execute_market(
            symbol="BTC",
            direction="long",
            notional_usd=500.0,
            mid_price=50_000.0,
        )
        # Should NOT raise
        fill = broker.execute_market(
            symbol="ETH",
            direction="long",
            notional_usd=200.0,
            mid_price=3_000.0,
        )
        assert fill.symbol == "ETH"

    def test_reopen_after_close_allowed(self, db):
        """After a position is closed, a new one for the same symbol is permitted."""
        from engine.execution.pnl import PnLTracker

        broker = PaperBroker(db)
        fill = broker.execute_market(
            symbol="SOL",
            direction="long",
            notional_usd=100.0,
            mid_price=200.0,
        )
        # Close it
        tracker = PnLTracker(db)
        tracker.close_position(position_id=fill.position_id, exit_price=210.0, reason="test")

        # Reopen — must succeed
        fill2 = broker.execute_market(
            symbol="SOL",
            direction="long",
            notional_usd=100.0,
            mid_price=205.0,
        )
        assert fill2.symbol == "SOL"
        assert fill2.position_id != fill.position_id

    def test_idempotency_key_bypass_dedup(self, db):
        """A repeated call with the SAME idempotency_key returns the original fill (not dedup error)."""
        broker = PaperBroker(db)
        idem = "test-idem-key-abc"
        fill1 = broker.execute_market(
            symbol="BTC",
            direction="long",
            notional_usd=500.0,
            mid_price=50_000.0,
            idempotency_key=idem,
        )
        # Same idempotency key → should return original fill, not deduplicate rejection
        fill2 = broker.execute_market(
            symbol="BTC",
            direction="long",
            notional_usd=500.0,
            mid_price=50_000.0,
            idempotency_key=idem,
        )
        assert fill1.order_id == fill2.order_id
        assert fill1.position_id == fill2.position_id


# ─────────────────────────────────────────────────────────────────────────────
# Bug 3: signal_log table exists in schema
# ─────────────────────────────────────────────────────────────────────────────


class TestSignalLogTable:
    def test_signal_log_table_exists(self, db):
        """signal_log table must be created by the schema migration."""
        tables = [r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "signal_log" in tables, "signal_log table not found in schema"

    def test_signal_log_columns(self, db):
        """signal_log must have the columns expected by dashboard/app.py."""
        cols = {str(r[1]) for r in db.conn.execute("PRAGMA table_info(signal_log)").fetchall()}
        required = {"producer_id", "domain", "confidence", "score", "created_at"}
        missing = required - cols
        assert not missing, f"signal_log missing columns: {missing}"

    def test_signal_log_insert(self, db):
        """Verify we can INSERT a row into signal_log without error."""
        db.conn.execute(
            "INSERT INTO signal_log (producer_id, domain, asset, direction, confidence, score) VALUES (?, ?, ?, ?, ?, ?)",
            ("technical-analysis", "technical", "BTC", "long", 0.72, 0.72),
        )
        db.conn.commit()
        count = db.conn.execute("SELECT COUNT(*) FROM signal_log").fetchone()[0]
        assert count == 1


# ─────────────────────────────────────────────────────────────────────────────
# Bug 5: OMS rejects duplicate positions (propagates through stack)
# ─────────────────────────────────────────────────────────────────────────────


class TestOMSDeduplication:
    def test_paper_broker_dedup_via_oms(self, tmp_path):
        """When preflight passes but paper broker sees a duplicate position,
        OMS.submit must return status='rejected' with reason 'duplicate_open_position'."""
        from unittest.mock import MagicMock

        from engine.core.config import Config
        from engine.core.types import TradeIntent
        from engine.execution.oms import OMS, default_sizer_from_config

        cfg = Config()
        _db = Database(db_path=tmp_path / "oms_test.db")

        # Use a permissive preflight that always approves
        mock_pf = MagicMock()
        mock_pf.run.return_value = MagicMock(approved=True, reasons=[], details={})

        # Use a permissive policy
        mock_policy = MagicMock()
        mock_policy.pretrade_check.return_value = None

        oms = OMS(
            config=cfg,
            db=_db,
            preflight=mock_pf,
            sizer=default_sizer_from_config(cfg),
            policy=mock_policy,
        )

        intent = TradeIntent(
            symbol="BTC",
            direction="long",
            size_pct=0.05,
            leverage=1.0,
            conviction_score=75.0,
            regime="BULL",
            rationale="test",
            stop_loss_pct=0.05,
            take_profit_pct=0.10,
        )

        # First fill
        result1 = oms.submit(intent, mid_price=50_000.0, equity_usd=10_000.0)
        assert result1.status == "filled", f"Expected 'filled', got {result1.status!r}: {result1.reasons}"

        # Second attempt on same symbol → dedup rejection from paper broker
        result2 = oms.submit(intent, mid_price=51_000.0, equity_usd=10_000.0)
        assert result2.status == "rejected"
        assert any("duplicate_open_position" in (r or "") for r in (result2.reasons or [])), (
            f"Expected 'duplicate_open_position' in reasons, got: {result2.reasons}"
        )

        _db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Bug 6: TA producer handles TradFi symbols gracefully
# ─────────────────────────────────────────────────────────────────────────────


class TestTAProducerTradFi:
    def test_spy_in_binance_missing(self):
        """SPY must be in _BINANCE_MISSING so it's skipped without crash."""
        from engine.producers.ta import TechnicalAnalysisProducer

        assert "SPY" in TechnicalAnalysisProducer._BINANCE_MISSING

    def test_qqq_in_binance_missing(self):
        """QQQ must be in _BINANCE_MISSING."""
        from engine.producers.ta import TechnicalAnalysisProducer

        assert "QQQ" in TechnicalAnalysisProducer._BINANCE_MISSING
