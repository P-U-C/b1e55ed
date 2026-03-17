"""Tests for engine.brain.stratification_recorder.

Verifies that benchmark comparison rows are correctly written to
signal_stratification when a position closes.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from engine.brain.stratification_recorder import _benchmark_pnl, record_benchmark_stratification
from engine.core.database import Database
from engine.core.events import EventType

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_db(tmp_path) -> Database:  # type: ignore[no-untyped-def]
    return Database(tmp_path / "test.db")


def _insert_conviction(db: Database, symbol: str, confidence: float) -> int:
    """Insert a conviction_scores row and return its rowid."""
    cycle_id = str(uuid.uuid4())
    node_id = str(uuid.uuid4())
    commitment_hash = f"hash-{uuid.uuid4()}"
    row_id_row = db.conn.execute(
        """INSERT INTO conviction_scores
           (cycle_id, node_id, symbol, direction, magnitude, timeframe, ts, commitment_hash, confidence)
           VALUES (?, ?, ?, 'long', 0.5, '24h', datetime('now'), ?, ?)""",
        (cycle_id, node_id, symbol, commitment_hash, confidence),
    )
    db.conn.commit()
    return row_id_row.lastrowid  # type: ignore[return-value]


def _get_conviction_row_id(db: Database, lastrowid: int) -> int:
    """Get the actual integer id of the conviction just inserted."""
    row = db.conn.execute("SELECT id FROM conviction_scores WHERE rowid = ?", (lastrowid,)).fetchone()
    assert row is not None
    return row[0]


def _insert_position(
    db: Database,
    *,
    position_id: str,
    symbol: str,
    direction: str,
    entry_price: float,
    exit_price: float,
    size_notional: float = 1000.0,
    opened_at: datetime | None = None,
    conviction_id: int | None = None,
) -> float:
    """Insert a closed position and return realized_pnl."""
    opened_at = opened_at or datetime.now(tz=UTC)
    closed_at = opened_at + timedelta(hours=1)

    qty = size_notional / entry_price
    if direction == "long":
        realized_pnl = (exit_price - entry_price) * qty
    else:
        realized_pnl = (entry_price - exit_price) * qty

    db.conn.execute(
        """INSERT INTO positions
           (id, platform, asset, direction, entry_price, size_notional,
            leverage, margin_type, opened_at, closed_at, status, realized_pnl, conviction_id)
           VALUES (?, 'paper', ?, ?, ?, ?,
                   1.0, 'isolated', ?, ?, 'closed', ?, ?)""",
        (
            position_id,
            symbol,
            direction,
            entry_price,
            size_notional,
            opened_at.isoformat(),
            closed_at.isoformat(),
            realized_pnl,
            conviction_id,
        ),
    )
    db.conn.commit()
    return realized_pnl


def _insert_benchmark_event(
    db: Database,
    *,
    source: str,
    symbol: str,
    direction: str,
    ts: datetime | None = None,
) -> None:
    """Insert a signal.benchmark.v1 event."""
    ts = ts or datetime.now(tz=UTC)
    eid = str(uuid.uuid4())
    payload = json.dumps({"source": source, "symbol": symbol, "direction": direction, "confidence": 0.0})
    db.conn.execute(
        "INSERT INTO events (id, type, ts, payload, hash) VALUES (?, ?, ?, ?, ?)",
        (eid, str(EventType.SIGNAL_BENCHMARK_V1), ts.isoformat(), payload, f"h-{eid}"),
    )
    db.conn.commit()


# ── unit tests ────────────────────────────────────────────────────────────────


class TestBenchmarkPnl:
    def test_same_direction(self) -> None:
        assert _benchmark_pnl(benchmark_direction="long", system_direction="long", system_pnl=100.0) == 100.0

    def test_opposite_direction(self) -> None:
        assert _benchmark_pnl(benchmark_direction="short", system_direction="long", system_pnl=100.0) == -100.0

    def test_flat_direction(self) -> None:
        assert _benchmark_pnl(benchmark_direction="flat", system_direction="long", system_pnl=100.0) == 0.0

    def test_case_insensitive(self) -> None:
        assert _benchmark_pnl(benchmark_direction="LONG", system_direction="long", system_pnl=50.0) == 50.0

    def test_short_vs_short(self) -> None:
        assert _benchmark_pnl(benchmark_direction="short", system_direction="short", system_pnl=-20.0) == -20.0


# ── integration tests ─────────────────────────────────────────────────────────


class TestRecordBenchmarkStratification:
    def test_basic_row_written(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """One benchmark signal → one row in signal_stratification."""
        db = _make_db(tmp_path)
        opened_at = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
        position_id = str(uuid.uuid4())

        # Insert conviction
        lastrowid = _insert_conviction(db, "BTC", confidence=0.70)
        conviction_id = _get_conviction_row_id(db, lastrowid)

        # Insert position (closed, long, profitable)
        _insert_position(
            db,
            position_id=position_id,
            symbol="BTC",
            direction="long",
            entry_price=80_000.0,
            exit_price=82_000.0,
            conviction_id=conviction_id,
            opened_at=opened_at,
        )

        # Insert benchmark signal 30 min before open
        bm_ts = opened_at - timedelta(minutes=30)
        _insert_benchmark_event(db, source="benchmark.flat", symbol="BTC", direction="flat", ts=bm_ts)

        n = record_benchmark_stratification(db=db, position_id=position_id)
        assert n == 1

        rows = db.fetchall("SELECT * FROM signal_stratification WHERE position_id = ?", (position_id,))
        assert len(rows) == 1
        row = rows[0]
        assert row["benchmark_name"] == "benchmark.flat"
        assert row["benchmark_direction"] == "flat"
        assert row["benchmark_pnl"] == pytest.approx(0.0)
        assert row["symbol"] == "BTC"
        assert row["bucket"] == "high"  # confidence=0.70 → high

    def test_multiple_benchmarks(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Multiple benchmark sources → one row per source."""
        db = _make_db(tmp_path)
        opened_at = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
        position_id = str(uuid.uuid4())

        lastrowid = _insert_conviction(db, "ETH", confidence=0.50)
        conviction_id = _get_conviction_row_id(db, lastrowid)

        realized = _insert_position(
            db,
            position_id=position_id,
            symbol="ETH",
            direction="long",
            entry_price=2000.0,
            exit_price=2100.0,
            size_notional=1000.0,
            conviction_id=conviction_id,
            opened_at=opened_at,
        )

        bm_ts = opened_at - timedelta(minutes=10)
        for src, direction in [
            ("benchmark.flat", "flat"),
            ("benchmark.momentum", "long"),
            ("benchmark.equal_weight", "short"),
        ]:
            _insert_benchmark_event(db, source=src, symbol="ETH", direction=direction, ts=bm_ts)

        n = record_benchmark_stratification(db=db, position_id=position_id)
        assert n == 3

        rows = db.fetchall(
            "SELECT benchmark_name, benchmark_pnl, system_pnl FROM signal_stratification WHERE position_id = ?",
            (position_id,),
        )
        assert len(rows) == 3

        by_name = {r["benchmark_name"]: r for r in rows}
        assert by_name["benchmark.flat"]["benchmark_pnl"] == pytest.approx(0.0)
        assert by_name["benchmark.momentum"]["benchmark_pnl"] == pytest.approx(realized)
        assert by_name["benchmark.equal_weight"]["benchmark_pnl"] == pytest.approx(-realized)
        # All rows should have the same system_pnl
        for r in rows:
            assert r["system_pnl"] == pytest.approx(realized)

    def test_skips_open_position(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """An open position → returns 0 and writes nothing."""
        db = _make_db(tmp_path)
        position_id = str(uuid.uuid4())

        db.conn.execute(
            """INSERT INTO positions
               (id, platform, asset, direction, entry_price, size_notional,
                leverage, margin_type, opened_at, status)
               VALUES (?, 'paper', 'SOL', 'long', 150.0, 1000.0,
                       1.0, 'isolated', datetime('now'), 'open')""",
            (position_id,),
        )
        db.conn.commit()

        n = record_benchmark_stratification(db=db, position_id=position_id)
        assert n == 0

        rows = db.fetchall("SELECT * FROM signal_stratification WHERE position_id = ?", (position_id,))
        assert len(rows) == 0

    def test_skips_when_no_benchmark_signals(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Closed position but no benchmark events → returns 0."""
        db = _make_db(tmp_path)
        opened_at = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
        position_id = str(uuid.uuid4())

        lastrowid = _insert_conviction(db, "BTC", confidence=0.55)
        conviction_id = _get_conviction_row_id(db, lastrowid)

        _insert_position(
            db,
            position_id=position_id,
            symbol="BTC",
            direction="short",
            entry_price=70_000.0,
            exit_price=68_000.0,
            conviction_id=conviction_id,
            opened_at=opened_at,
        )
        # No benchmark events inserted.

        n = record_benchmark_stratification(db=db, position_id=position_id)
        assert n == 0

    def test_skips_wrong_symbol(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Benchmark events for a different symbol are ignored."""
        db = _make_db(tmp_path)
        opened_at = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
        position_id = str(uuid.uuid4())

        lastrowid = _insert_conviction(db, "BTC", confidence=0.55)
        conviction_id = _get_conviction_row_id(db, lastrowid)

        _insert_position(
            db,
            position_id=position_id,
            symbol="BTC",
            direction="long",
            entry_price=80_000.0,
            exit_price=81_000.0,
            conviction_id=conviction_id,
            opened_at=opened_at,
        )

        # Benchmark event for ETH, not BTC
        bm_ts = opened_at - timedelta(minutes=5)
        _insert_benchmark_event(db, source="benchmark.flat", symbol="ETH", direction="flat", ts=bm_ts)

        n = record_benchmark_stratification(db=db, position_id=position_id)
        assert n == 0

    def test_missing_position(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Non-existent position_id → returns 0 gracefully."""
        db = _make_db(tmp_path)
        n = record_benchmark_stratification(db=db, position_id="does-not-exist")
        assert n == 0

    def test_confidence_band_low(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Low confidence conviction → bucket='low' in stratification row."""
        db = _make_db(tmp_path)
        opened_at = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
        position_id = str(uuid.uuid4())

        lastrowid = _insert_conviction(db, "SOL", confidence=0.25)
        conviction_id = _get_conviction_row_id(db, lastrowid)

        _insert_position(
            db,
            position_id=position_id,
            symbol="SOL",
            direction="long",
            entry_price=100.0,
            exit_price=110.0,
            conviction_id=conviction_id,
            opened_at=opened_at,
        )

        bm_ts = opened_at - timedelta(minutes=5)
        _insert_benchmark_event(db, source="benchmark.flat", symbol="SOL", direction="flat", ts=bm_ts)

        n = record_benchmark_stratification(db=db, position_id=position_id)
        assert n == 1

        row = db.fetchone(
            "SELECT bucket, system_confidence FROM signal_stratification WHERE position_id = ?",
            (position_id,),
        )
        assert row["bucket"] == "low"
        assert row["system_confidence"] == pytest.approx(0.25)
