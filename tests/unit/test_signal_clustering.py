"""Tests for signal clustering and first-mover weighting."""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest

from engine.spi.admission import _ensure_tables, _horizon_matches, accept_signal


class FakeDB:
    """Minimal DB wrapper matching engine.core.database.Database interface."""

    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA journal_mode=WAL")

    def execute(self, sql, params=()):
        return self.conn.execute(sql, params)

    def fetchone(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()

    def fetchall(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()

    def __hash__(self):
        return id(self)


@pytest.fixture
def db():
    d = FakeDB()
    _ensure_tables(d)
    return d


def _make_signal(db, producer_id="prod-1", signal_client_id="cli-1", submission_id="sub-1", symbol="BTC", direction="bullish", confidence=0.8, horizon_hours=4):
    with patch("engine.spi.price_feeds.fetch_price_usd", return_value=50000.0), patch("engine.spi.lifecycle.maybe_auto_promote"):
        return accept_signal(
            producer_id=producer_id,
            signal_client_id=signal_client_id,
            submission_id=submission_id,
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            horizon_hours=horizon_hours,
            db=db,
        )


def test_two_identical_signals_get_clustered(db):
    """Two signals with same symbol+direction+confidence should cluster."""
    s1 = _make_signal(db, producer_id="prod-1", signal_client_id="c1", submission_id="s1")
    s2 = _make_signal(db, producer_id="prod-2", signal_client_id="c2", submission_id="s2")

    assert s1.cluster_id is not None
    assert s1.cluster_id == s2.cluster_id
    assert s1.cluster_position == 1
    assert s2.cluster_position == 2


def test_first_mover_weight(db):
    """First mover gets 1.0, second gets 1/(2^1.5) ≈ 0.354."""
    s1 = _make_signal(db, producer_id="prod-1", signal_client_id="c1", submission_id="s1")
    s2 = _make_signal(db, producer_id="prod-2", signal_client_id="c2", submission_id="s2")

    assert s1.cluster_weight == 1.0
    assert abs(s2.cluster_weight - 1.0 / (2**1.5)) < 0.001


def test_different_symbol_not_clustered(db):
    """Different symbols should NOT be clustered together."""
    s1 = _make_signal(db, producer_id="prod-1", signal_client_id="c1", submission_id="s1", symbol="BTC")
    s2 = _make_signal(db, producer_id="prod-2", signal_client_id="c2", submission_id="s2", symbol="ETH")

    assert s1.cluster_id != s2.cluster_id


def test_different_direction_not_clustered(db):
    """Different directions should NOT be clustered together."""
    s1 = _make_signal(db, producer_id="prod-1", signal_client_id="c1", submission_id="s1", direction="bullish")
    s2 = _make_signal(db, producer_id="prod-2", signal_client_id="c2", submission_id="s2", direction="bearish")

    assert s1.cluster_id != s2.cluster_id


def test_karma_resolution_applies_cluster_weight(db):
    """Resolution should multiply karma_delta by cluster_weight."""
    from engine.spi.resolution import _get_cluster_weight

    # Insert a signal with cluster_weight=0.5
    _ensure_tables(db)
    db.execute(
        """INSERT INTO spi_signals (
            signal_id, signal_client_id, submission_id, producer_id,
            ingress_mode, symbol, direction, confidence, horizon_hours,
            submitted_at, attribution_window_start, attribution_window_end,
            status, cluster_weight, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "sig-test",
            "c-test",
            "s-test",
            "p-test",
            "adapter",
            "BTC",
            "bullish",
            0.8,
            4,
            "2026-01-01T00:00:00",
            "2026-01-01T00:00:00",
            "2026-01-01T00:00:00",
            "accepted",
            0.354,
            "2026-01-01T00:00:00",
            "2026-01-01T00:00:00",
        ),
    )

    weight = _get_cluster_weight(db, "sig-test")
    assert abs(weight - 0.354) < 0.001


def test_cluster_weight_default_for_old_signals(db):
    """Signals without cluster_weight should default to 1.0."""
    from engine.spi.resolution import _get_cluster_weight

    _ensure_tables(db)
    db.execute(
        """INSERT INTO spi_signals (
            signal_id, signal_client_id, submission_id, producer_id,
            ingress_mode, symbol, direction, confidence, horizon_hours,
            submitted_at, attribution_window_start, attribution_window_end,
            status, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "sig-old",
            "c-old",
            "s-old",
            "p-old",
            "adapter",
            "BTC",
            "bullish",
            0.8,
            4,
            "2026-01-01T00:00:00",
            "2026-01-01T00:00:00",
            "2026-01-01T00:00:00",
            "accepted",
            "2026-01-01T00:00:00",
            "2026-01-01T00:00:00",
        ),
    )

    weight = _get_cluster_weight(db, "sig-old")
    assert weight == 1.0


def test_schema_migration_idempotent(db):
    """Running _ensure_tables twice should not error."""
    from engine.spi.admission import _TABLES_ENSURED

    _TABLES_ENSURED.discard(db)
    _ensure_tables(db)  # second call — should be fine


def test_horizon_matching():
    """Test horizon bucket matching."""
    assert _horizon_matches(1, 2) is True
    assert _horizon_matches(4, 4) is True
    assert _horizon_matches(1, 4) is False  # different buckets, >2h apart
    assert _horizon_matches(1, 24) is False
    assert _horizon_matches(12, 12) is True
    assert _horizon_matches(23, 24) is True  # within ±2h
