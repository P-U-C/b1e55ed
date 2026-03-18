"""Unit tests for the SPI admission pipeline (Phase 1B).

Tests cover:
- scoring pure functions (Brier, karma delta, direction correctness)
- accept_signal() happy path and idempotency
- database schema creation via _ensure_tables
"""

from __future__ import annotations

import sqlite3

import pytest

from engine.spi.admission import _ensure_tables, accept_signal
from engine.spi.models import AcceptedSignal
from engine.spi.scoring import (
    compute_brier,
    compute_karma_delta,
    determine_direction_correct,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _SimpleDB:
    """Minimal in-memory SQLite wrapper that mimics engine.core.database.Database."""

    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def fetchone(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()


@pytest.fixture()
def db() -> _SimpleDB:
    return _SimpleDB()


# ---------------------------------------------------------------------------
# scoring.py — pure function tests
# ---------------------------------------------------------------------------


class TestComputeBrier:
    def test_perfect_bullish_correct(self):
        """Maximum confidence, outcome correct → minimal Brier score."""
        # confidence=1.0, correct → (1.0 - 1.0)^2 = 0.0
        assert compute_brier(1.0, True) == pytest.approx(0.0)

    def test_perfect_bullish_incorrect(self):
        """Maximum confidence, outcome incorrect → maximum Brier score."""
        # confidence=1.0, wrong → (1.0 - 0.0)^2 = 1.0
        assert compute_brier(1.0, False) == pytest.approx(1.0)

    def test_zero_confidence_correct(self):
        """Zero confidence, outcome correct → maximum Brier score (1.0)."""
        assert compute_brier(0.0, True) == pytest.approx(1.0)

    def test_zero_confidence_incorrect(self):
        """Zero confidence, outcome incorrect → Brier = 0."""
        assert compute_brier(0.0, False) == pytest.approx(0.0)

    def test_half_confidence(self):
        """0.5 confidence either way → 0.25 Brier."""
        assert compute_brier(0.5, True) == pytest.approx(0.25)
        assert compute_brier(0.5, False) == pytest.approx(0.25)

    def test_typical_signal(self):
        """Typical signal: 0.75 confidence, correct → (0.75 - 1)^2 = 0.0625."""
        assert compute_brier(0.75, True) == pytest.approx(0.0625)


class TestComputeKarmaDelta:
    def test_perfect_epoch_increases_karma(self):
        """Epoch Brier of 0 (perfect epoch) → epoch_karma=1.0 → karma should rise."""
        delta = compute_karma_delta(0.5, 0.0)
        # new = 0.7*0.5 + 0.3*1.0 = 0.35 + 0.30 = 0.65 → delta = +0.15
        assert delta == pytest.approx(0.15)

    def test_bad_epoch_decreases_karma(self):
        """Epoch Brier of 1 (worst epoch) → epoch_karma=0.0 → karma should fall."""
        delta = compute_karma_delta(0.5, 1.0)
        # new = 0.7*0.5 + 0.3*0.0 = 0.35 → delta = -0.15
        assert delta == pytest.approx(-0.15)

    def test_karma_clamped_at_zero(self):
        """Karma cannot go below 0.0."""
        # Starting from 0.0 karma with worst epoch → stays 0.
        delta = compute_karma_delta(0.0, 1.0)
        # new = 0.7*0.0 + 0.3*0.0 = 0.0, clamped to 0.0 → delta = 0.0
        assert delta == pytest.approx(0.0)

    def test_karma_clamped_at_one(self):
        """Karma cannot exceed 1.0."""
        delta = compute_karma_delta(1.0, 0.0)
        # new = 0.7*1.0 + 0.3*1.0 = 1.0, clamped to 1.0 → delta = 0.0
        assert delta == pytest.approx(0.0)

    def test_custom_smoothing_factor(self):
        """Custom smoothing factor is respected."""
        delta = compute_karma_delta(0.5, 0.0, smoothing_factor=0.5)
        # new = 0.5*0.5 + 0.5*1.0 = 0.75 → delta = 0.25
        assert delta == pytest.approx(0.25)


class TestDetermineDirectionCorrect:
    def test_bullish_price_up(self):
        assert determine_direction_correct("bullish", 5.0) is True

    def test_bullish_price_down(self):
        assert determine_direction_correct("bullish", -3.0) is False

    def test_bearish_price_down(self):
        assert determine_direction_correct("bearish", -5.0) is True

    def test_bearish_price_up(self):
        assert determine_direction_correct("bearish", 3.0) is False

    def test_neutral_small_move(self):
        assert determine_direction_correct("neutral", 1.5) is True
        assert determine_direction_correct("neutral", -1.9) is True

    def test_neutral_large_move(self):
        assert determine_direction_correct("neutral", 2.1) is False
        assert determine_direction_correct("neutral", -2.1) is False

    def test_neutral_exact_boundary(self):
        """Exactly 2.0% should be incorrect (not < 2.0)."""
        assert determine_direction_correct("neutral", 2.0) is False

    def test_bullish_zero_change(self):
        """Zero price change is not bullish-correct (not > 0)."""
        assert determine_direction_correct("bullish", 0.0) is False


# ---------------------------------------------------------------------------
# admission.py — accept_signal() integration tests
# ---------------------------------------------------------------------------


class TestAcceptSignal:
    def test_writes_to_spi_signals(self, db: _SimpleDB):
        """accept_signal() writes a row to spi_signals."""
        result = accept_signal(
            producer_id="test_producer",
            signal_client_id="client-001",
            submission_id="sub-001",
            symbol="BTC",
            direction="bullish",
            confidence=0.75,
            horizon_hours=24,
            db=db,
        )

        row = db.fetchone("SELECT * FROM spi_signals WHERE signal_id = ?", (result.signal_id,))
        assert row is not None
        assert row["producer_id"] == "test_producer"
        assert row["symbol"] == "BTC"
        assert row["direction"] == "bullish"

    def test_returns_accepted_signal(self, db: _SimpleDB):
        """accept_signal() returns an AcceptedSignal with correct fields."""
        result = accept_signal(
            producer_id="my_producer",
            signal_client_id="ck-xyz",
            submission_id="s-xyz",
            symbol="ETH",
            direction="bearish",
            confidence=0.65,
            horizon_hours=48,
            db=db,
        )

        assert isinstance(result, AcceptedSignal)
        assert result.producer_id == "my_producer"
        assert result.symbol == "ETH"
        assert result.direction == "bearish"
        assert result.confidence == pytest.approx(0.65)
        assert result.horizon_hours == 48
        assert result.status == "accepted"
        assert result.ingress_mode == "adapter"

    def test_idempotent_duplicate_submission(self, db: _SimpleDB):
        """Duplicate signal_client_id + submission_id is silently ignored (INSERT OR IGNORE)."""
        kwargs = dict(
            producer_id="prod_a",
            signal_client_id="idem-key",
            submission_id="idem-sub",
            symbol="SOL",
            direction="bullish",
            confidence=0.80,
            horizon_hours=12,
            db=db,
        )
        accept_signal(**kwargs)
        # Second call with same keys must not raise and must not duplicate.
        accept_signal(**kwargs)

        rows = db.fetchall("SELECT * FROM spi_signals WHERE signal_client_id = ?", ("idem-key",))
        assert len(rows) == 1

    def test_event_id_stored(self, db: _SimpleDB):
        """event_id is persisted when provided."""
        result = accept_signal(
            producer_id="p1",
            signal_client_id="ev-001",
            submission_id="ev-sub-001",
            symbol="BTC",
            direction="neutral",
            confidence=0.60,
            horizon_hours=6,
            event_id="evt-abc-123",
            db=db,
        )

        row = db.fetchone("SELECT event_id FROM spi_signals WHERE signal_id = ?", (result.signal_id,))
        assert row["event_id"] == "evt-abc-123"

    def test_signal_payload_serialized(self, db: _SimpleDB):
        """signal_payload dict is JSON-serialized and stored."""
        payload = {"price": 42000.0, "source": "binance"}
        result = accept_signal(
            producer_id="p2",
            signal_client_id="pl-001",
            submission_id="pl-sub-001",
            symbol="BTC",
            direction="bullish",
            confidence=0.70,
            horizon_hours=8,
            signal_payload=payload,
            db=db,
        )

        import json

        row = db.fetchone(
            "SELECT signal_payload_json FROM spi_signals WHERE signal_id = ?",
            (result.signal_id,),
        )
        assert row is not None
        stored = json.loads(row["signal_payload_json"])
        assert stored["price"] == pytest.approx(42000.0)

    def test_ensure_tables_creates_all_spi_tables(self, db: _SimpleDB):
        """_ensure_tables() creates all four SPI tables."""
        _ensure_tables(db)

        tables = {row[0] for row in db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "spi_signals" in tables
        assert "spi_outcomes" in tables
        assert "spi_karma" in tables
        assert "spi_producers" in tables

    def test_native_ingress_mode(self, db: _SimpleDB):
        """ingress_mode='native' is stored correctly."""
        result = accept_signal(
            producer_id="gateway_p",
            signal_client_id="gw-001",
            submission_id="gw-sub-001",
            symbol="AVAX",
            direction="bullish",
            confidence=0.85,
            horizon_hours=72,
            ingress_mode="native",
            db=db,
        )

        row = db.fetchone(
            "SELECT ingress_mode FROM spi_signals WHERE signal_id = ?",
            (result.signal_id,),
        )
        assert row["ingress_mode"] == "native"

    def test_attribution_window_set(self, db: _SimpleDB):
        """attribution_window_start and attribution_window_end are set."""
        result = accept_signal(
            producer_id="pw",
            signal_client_id="aw-001",
            submission_id="aw-sub-001",
            symbol="SOL",
            direction="bearish",
            confidence=0.72,
            horizon_hours=24,
            db=db,
        )
        assert result.attribution_window_start != ""
        assert result.attribution_window_end != ""
        # Window end must be after window start.
        assert result.attribution_window_end > result.attribution_window_start

    def test_multiple_signals_same_producer(self, db: _SimpleDB):
        """Multiple different signals for the same producer are all stored."""
        for i in range(3):
            accept_signal(
                producer_id="multi_prod",
                signal_client_id=f"multi-{i}",
                submission_id=f"multi-sub-{i}",
                symbol="ETH",
                direction="bullish",
                confidence=0.70 + i * 0.05,
                horizon_hours=12,
                db=db,
            )

        rows = db.fetchall("SELECT * FROM spi_signals WHERE producer_id = ?", ("multi_prod",))
        assert len(rows) == 3
