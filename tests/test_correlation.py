"""Tests for P2.3 — pairwise producer correlation tracking."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    UTC = UTC  # noqa: N806

import pytest

from engine.brain.correlation import (
    _pearson,
    get_correlation_matrix,
    update_all_pairs,
    update_correlation_pair,
)
from engine.core.database import Database


def _ts(hours_ago: int) -> str:
    dt = datetime.now(tz=UTC) - timedelta(hours=hours_ago)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _seed(db: Database, *, producer: str, score: float, hours_ago: int, symbol: str = "BTC") -> None:
    """Insert a raw conviction_log row — no dependency on other modules."""
    with db.conn:
        db.conn.execute(
            """
            INSERT INTO conviction_log (
                cycle_id, symbol, domain, domain_score, domain_weight,
                weighted_contribution, producer_name, ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"cycle-{producer}-{hours_ago}",
                symbol,
                "technical",
                score,
                1.0,
                score,
                producer,
                _ts(hours_ago),
            ),
        )


@pytest.fixture()
def db(temp_dir: Path) -> Database:
    database = Database(temp_dir / "brain.db")
    try:
        yield database
    finally:
        database.close()


# ------------------------------------------------------------------
# _pearson unit tests
# ------------------------------------------------------------------


def test_pearson_perfect_positive() -> None:
    assert _pearson([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_pearson_perfect_negative() -> None:
    assert _pearson([1.0, 2.0, 3.0], [3.0, 2.0, 1.0]) == pytest.approx(-1.0)


def test_pearson_constant_series_returns_none() -> None:
    assert _pearson([5.0, 5.0, 5.0], [1.0, 2.0, 3.0]) is None


def test_pearson_too_few_points_returns_none() -> None:
    assert _pearson([1.0, 2.0], [1.0, 2.0]) is None


# ------------------------------------------------------------------
# update_correlation_pair
# ------------------------------------------------------------------


def test_update_pair_returns_none_insufficient_data(db: Database) -> None:
    # Only 2 overlapping hour-buckets → below threshold of 3
    _seed(db, producer="pa", score=1.0, hours_ago=2)
    _seed(db, producer="pb", score=2.0, hours_ago=2)
    _seed(db, producer="pa", score=2.0, hours_ago=1)
    _seed(db, producer="pb", score=4.0, hours_ago=1)

    r = update_correlation_pair(db, "pa", "pb")
    assert r is None
    count = int(db.conn.execute("SELECT COUNT(*) FROM producer_correlation").fetchone()[0])
    assert count == 0


def test_update_pair_computes_and_stores(db: Database) -> None:
    for h, (a, b) in enumerate([(1.0, 2.0), (2.0, 4.0), (3.0, 6.0)], start=1):
        _seed(db, producer="pa", score=a, hours_ago=h)
        _seed(db, producer="pb", score=b, hours_ago=h)

    r = update_correlation_pair(db, "pa", "pb", asset="BTC", regime="bull", window_days=30)
    assert r == pytest.approx(1.0)

    row = db.conn.execute(
        "SELECT producer_a, producer_b, asset, regime, pearson_r, sample_count, window_days "
        "FROM producer_correlation WHERE producer_a = ? AND producer_b = ?",
        ("pa", "pb"),
    ).fetchone()
    assert row is not None
    assert str(row["producer_a"]) == "pa"
    assert str(row["producer_b"]) == "pb"
    assert str(row["asset"]) == "BTC"
    assert str(row["regime"]) == "bull"
    assert float(row["pearson_r"]) == pytest.approx(1.0)
    assert int(row["sample_count"]) == 3
    assert int(row["window_days"]) == 30


def test_update_pair_idempotent_upsert(db: Database) -> None:
    for h, (a, b) in enumerate([(1.0, 2.0), (2.0, 4.0), (3.0, 6.0)], start=1):
        _seed(db, producer="pa", score=a, hours_ago=h)
        _seed(db, producer="pb", score=b, hours_ago=h)

    first = update_correlation_pair(db, "pa", "pb", asset="BTC", regime="unknown")
    second = update_correlation_pair(db, "pa", "pb", asset="BTC", regime="unknown")
    assert first == pytest.approx(1.0)
    assert second == pytest.approx(1.0)

    count = int(
        db.conn.execute(
            "SELECT COUNT(*) FROM producer_correlation "
            "WHERE producer_a = ? AND producer_b = ? AND asset = ? AND regime = ?",
            ("pa", "pb", "BTC", "unknown"),
        ).fetchone()[0]
    )
    assert count == 1


# ------------------------------------------------------------------
# update_all_pairs
# ------------------------------------------------------------------


def test_update_all_pairs_two_producers(db: Database) -> None:
    for h, (a, b) in enumerate([(1.0, 2.0), (2.0, 4.0), (3.0, 6.0)], start=1):
        _seed(db, producer="pa", score=a, hours_ago=h)
        _seed(db, producer="pb", score=b, hours_ago=h)

    results = update_all_pairs(db)
    assert list(results.keys()) == [("pa", "pb")]
    assert results[("pa", "pb")] == pytest.approx(1.0)


# ------------------------------------------------------------------
# get_correlation_matrix
# ------------------------------------------------------------------


def test_get_matrix_empty(db: Database) -> None:
    assert get_correlation_matrix(db) == []


def test_get_matrix_after_update(db: Database) -> None:
    for h, (a, b) in enumerate([(1.0, 3.0), (2.0, 2.0), (3.0, 1.0)], start=1):
        _seed(db, producer="pa", score=a, hours_ago=h)
        _seed(db, producer="pb", score=b, hours_ago=h)

    update_correlation_pair(db, "pa", "pb", asset="BTC", regime="unknown")
    rows = get_correlation_matrix(db)

    assert len(rows) == 1
    row = rows[0]
    assert row["producer_a"] == "pa"
    assert row["producer_b"] == "pb"
    assert row["asset"] == "BTC"
    assert row["regime"] == "unknown"
    assert row["pearson_r"] == pytest.approx(-1.0)
    assert row["sample_count"] == 3
    assert row["window_days"] == 30
