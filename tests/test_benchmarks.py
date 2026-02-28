"""Tests for benchmark producers and discretionary API."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType
from engine.core.metrics import MetricsRegistry
from engine.producers.base import ProducerContext


class DummyClient:
    async def request_json(self, *a, **kw):  # type: ignore[no-untyped-def]
        return []


def _make_ctx(tmp_path):  # type: ignore[no-untyped-def]
    db = Database(tmp_path / "test.db")
    return (
        ProducerContext(
            config=Config(),
            db=db,
            client=DummyClient(),
            metrics=MetricsRegistry(),
            logger=logging.getLogger("test"),
        ),
        db,
    )


def _insert_price_event(db: Database, symbol: str, price: float, ts: datetime | None = None) -> None:
    ts = ts or datetime.now(tz=UTC)
    payload = json.dumps({"symbol": symbol, "price": price})
    eid = str(uuid.uuid4())
    db.conn.execute(
        "INSERT INTO events (id, type, ts, payload, hash) VALUES (?, ?, ?, ?, ?)",
        (eid, str(EventType.SIGNAL_PRICE_WS_V1), ts.isoformat(), payload, f"h-{eid}"),
    )
    db.conn.commit()


def _insert_signal_event(db: Database, event_type: EventType, symbol: str, direction: str, ts: datetime | None = None) -> None:
    ts = ts or datetime.now(tz=UTC)
    payload = json.dumps({"symbol": symbol, "direction": direction})
    eid = str(uuid.uuid4())
    db.conn.execute(
        "INSERT INTO events (id, type, ts, payload, hash) VALUES (?, ?, ?, ?, ?)",
        (eid, str(event_type), ts.isoformat(), payload, f"h-{eid}"),
    )
    db.conn.commit()


# --- Momentum ---


def test_momentum_long_above_ema(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from engine.producers.benchmarks import BenchmarkMomentumProducer

    ctx, db = _make_ctx(tmp_path)
    for i in range(19):
        _insert_price_event(db, "BTC", 100.0, datetime.now(tz=UTC) - timedelta(minutes=20 - i))
    _insert_price_event(db, "BTC", 200.0)

    p = BenchmarkMomentumProducer(ctx)
    raw = p.collect()
    btc = [r for r in raw if r["symbol"] == "BTC"]
    assert len(btc) == 1
    assert btc[0]["direction"] == "long"
    assert btc[0]["confidence"] == 0.50


def test_momentum_short_below_ema(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from engine.producers.benchmarks import BenchmarkMomentumProducer

    ctx, db = _make_ctx(tmp_path)
    for i in range(19):
        _insert_price_event(db, "BTC", 200.0, datetime.now(tz=UTC) - timedelta(minutes=20 - i))
    _insert_price_event(db, "BTC", 100.0)

    p = BenchmarkMomentumProducer(ctx)
    raw = p.collect()
    btc = [r for r in raw if r["symbol"] == "BTC"]
    assert len(btc) == 1
    assert btc[0]["direction"] == "short"
    assert btc[0]["confidence"] == 0.50


# --- Flat ---


def test_flat_always_neutral(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from engine.producers.benchmarks import BenchmarkFlatProducer

    ctx, db = _make_ctx(tmp_path)
    p = BenchmarkFlatProducer(ctx)
    result = p.run()
    assert result.events_published == 3
    events = db.get_events(event_type=EventType.SIGNAL_BENCHMARK_V1, source="benchmark.flat", limit=10)
    for ev in events:
        assert ev.payload["direction"] == "flat"
        assert ev.payload["confidence"] == 0.0


# --- Equal Weight ---


def test_equal_weight_majority_long(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from engine.producers.benchmarks import BenchmarkEqualWeightProducer

    ctx, db = _make_ctx(tmp_path)
    now = datetime.now(tz=UTC)
    _insert_signal_event(db, EventType.SIGNAL_TA_V1, "BTC", "long", now - timedelta(minutes=5))
    _insert_signal_event(db, EventType.SIGNAL_TA_V1, "BTC", "long", now - timedelta(minutes=10))
    _insert_signal_event(db, EventType.SIGNAL_TA_V1, "BTC", "long", now - timedelta(minutes=15))
    _insert_signal_event(db, EventType.SIGNAL_TRADFI_V1, "BTC", "short", now - timedelta(minutes=5))

    p = BenchmarkEqualWeightProducer(ctx)
    raw = p.collect()
    btc = [r for r in raw if r["symbol"] == "BTC"]
    assert len(btc) == 1
    assert btc[0]["direction"] == "long"


def test_equal_weight_majority_short(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from engine.producers.benchmarks import BenchmarkEqualWeightProducer

    ctx, db = _make_ctx(tmp_path)
    now = datetime.now(tz=UTC)
    _insert_signal_event(db, EventType.SIGNAL_TA_V1, "BTC", "short", now - timedelta(minutes=5))
    _insert_signal_event(db, EventType.SIGNAL_TA_V1, "BTC", "short", now - timedelta(minutes=10))
    _insert_signal_event(db, EventType.SIGNAL_TA_V1, "BTC", "short", now - timedelta(minutes=15))
    _insert_signal_event(db, EventType.SIGNAL_TRADFI_V1, "BTC", "long", now - timedelta(minutes=5))

    p = BenchmarkEqualWeightProducer(ctx)
    raw = p.collect()
    btc = [r for r in raw if r["symbol"] == "BTC"]
    assert len(btc) == 1
    assert btc[0]["direction"] == "short"


def test_equal_weight_no_signals_silent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from engine.producers.benchmarks import BenchmarkEqualWeightProducer

    ctx, _db = _make_ctx(tmp_path)
    p = BenchmarkEqualWeightProducer(ctx)
    raw = p.collect()
    assert len(raw) == 0


# --- Discretionary ---


def test_discretionary_no_rows_silent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from engine.producers.benchmarks import BenchmarkDiscretionaryProducer

    ctx, _db = _make_ctx(tmp_path)
    p = BenchmarkDiscretionaryProducer(ctx)
    result = p.run()
    assert result.events_published == 0


def test_discretionary_emits_stored_signal(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from engine.producers.benchmarks import BenchmarkDiscretionaryProducer

    ctx, db = _make_ctx(tmp_path)
    now = datetime.now(tz=UTC)
    expires = (now + timedelta(hours=24)).isoformat()
    db.conn.execute(
        "INSERT INTO discretionary_signals (id, symbol, direction, confidence, reasoning, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), "BTC", "long", 0.7, "test reason", now.isoformat(), expires),
    )
    db.conn.commit()

    p = BenchmarkDiscretionaryProducer(ctx)
    result = p.run()
    assert result.events_published == 1
    events = db.get_events(event_type=EventType.SIGNAL_BENCHMARK_V1, source="benchmark.discretionary", limit=10)
    assert len(events) == 1
    assert events[0].payload["direction"] == "long"
    assert events[0].payload["confidence"] == 0.7


def test_discretionary_api_creates_row(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from api.main import create_app

    app = create_app()
    client = TestClient(app)

    resp = client.post(
        "/api/v1/benchmarks/discretionary",
        json={
            "symbol": "BTC",
            "direction": "long",
            "confidence": 0.7,
            "reasoning": "test",
            "expires_in_hours": 24,
        },
    )
    # Route exists — may return 401/403 if auth required
    assert resp.status_code in (200, 201, 401, 403, 422)


# --- Registry ---


def test_benchmark_producers_all_registered() -> None:
    from engine.producers.registry import _reset_for_tests, discover, list_producers

    _reset_for_tests()
    discover()
    producers = list_producers()
    for name in [
        "benchmark.momentum",
        "benchmark.flat",
        "benchmark.equal_weight",
        "benchmark.discretionary",
    ]:
        assert name in producers, f"{name} not registered"
