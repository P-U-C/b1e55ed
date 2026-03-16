"""Tests for engine.brain.performance_aggregator — P4.4"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

try:
    from datetime import UTC
except ImportError:  # pragma: no cover

    UTC = UTC

from engine.brain.performance_aggregator import PerformanceAggregator
from engine.core.database import Database
from engine.core.events import EventType


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def _insert_outcome(
    db: Database,
    *,
    producer_id: str = "tradfi-basis",
    asset: str = "BTC",
    horizon: str = "24h",
    forecast_action: str = "long",
    forecast_confidence: float = 0.7,
    direction_correct: bool = True,
    brier_score: float | None = None,
    regime_at_forecast: str = "unknown",
    ts: datetime | None = None,
) -> str:
    ts = ts or datetime.now(tz=UTC)
    if brier_score is None:
        outcome_binary = 1.0 if direction_correct else 0.0
        brier_score = (forecast_confidence - outcome_binary) ** 2

    payload = {
        "forecast_event_id": str(uuid.uuid4()),
        "producer_id": producer_id,
        "asset": asset,
        "horizon": horizon,
        "forecast_action": forecast_action,
        "forecast_confidence": forecast_confidence,
        "forecast_price": 100.0,
        "actual_price": 105.0 if direction_correct else 95.0,
        "return_actual_pct": 5.0 if direction_correct else -5.0,
        "direction_correct": direction_correct,
        "brier_score": brier_score,
        "regime_at_forecast": regime_at_forecast,
        "resolved_at": ts.timestamp(),
    }
    ev = db.append_event(
        event_type=EventType.FORECAST_OUTCOME_V1,
        payload=payload,
        source="brain.outcome_resolver",
        ts=ts,
    )
    return str(ev.id)


# ---------------------------------------------------------------------------
# Core aggregator tests
# ---------------------------------------------------------------------------


def test_aggregator_zero_outcomes(tmp_path) -> None:
    """Aggregator with 0 outcomes → returns empty stats, no error."""
    db = Database(tmp_path / "brain.db")
    agg = PerformanceAggregator(db)
    result = agg.compute()
    assert result["outcome_count"] == 0
    assert result["producer_rows"] == 0
    assert result["correlation_rows"] == 0


def test_aggregator_below_min_forecasts(tmp_path) -> None:
    """Aggregator with < MIN_FORECASTS → win_rate=None via get_producer_stats."""
    db = Database(tmp_path / "brain.db")

    # Insert 3 outcomes (below MIN_FORECASTS_FOR_STATS=5)
    for _ in range(3):
        _insert_outcome(db, direction_correct=True)

    agg = PerformanceAggregator(db)
    agg.compute()

    stats = agg.get_producer_stats("tradfi-basis", "BTC", "24h")
    assert stats is None  # insufficient data returns None


def test_aggregator_win_rate_correct(tmp_path) -> None:
    """Aggregator with 10 outcomes, 7 correct → win_rate=0.7."""
    db = Database(tmp_path / "brain.db")

    for i in range(10):
        _insert_outcome(db, direction_correct=(i < 7))

    agg = PerformanceAggregator(db)
    result = agg.compute()
    assert result["outcome_count"] == 10
    assert result["producer_rows"] > 0

    stats = agg.get_producer_stats("tradfi-basis", "BTC", "24h", regime="all")
    assert stats is not None
    assert stats["forecast_count"] == 10
    assert abs(stats["win_rate"] - 0.7) < 1e-9


def test_correlation_always_agree(tmp_path) -> None:
    """Two producers always agree → agreement_rate=1.0."""
    db = Database(tmp_path / "brain.db")

    now = datetime.now(tz=UTC)
    for i in range(10):
        # Create matching forecast timestamps in same 2h bucket
        ts = now - timedelta(hours=2 * i + 1)

        # Producer A forecast
        fid_a = str(uuid.uuid4())
        db.append_event(
            event_type=EventType.FORECAST_V1,
            payload={
                "forecast_id": fid_a,
                "asset": "BTC",
                "horizon": "24h",
                "action": "long",
                "confidence": 0.7,
                "source": "producer-a@1.0",
                "regime_tag": "unknown",
                "lifecycle_state": "new",
                "visible_signal_refs": [],
                "used_signal_refs": [],
            },
            source="producer-a",
            ts=ts,
        )

        # Producer B forecast at same time
        fid_b = str(uuid.uuid4())
        db.append_event(
            event_type=EventType.FORECAST_V1,
            payload={
                "forecast_id": fid_b,
                "asset": "BTC",
                "horizon": "24h",
                "action": "long",
                "confidence": 0.6,
                "source": "producer-b@1.0",
                "regime_tag": "unknown",
                "lifecycle_state": "new",
                "visible_signal_refs": [],
                "used_signal_refs": [],
            },
            source="producer-b",
            ts=ts,
        )

        # Get their event IDs
        rows = db.conn.execute(
            "SELECT id FROM events WHERE type = ? ORDER BY rowid DESC LIMIT 2",
            (EventType.FORECAST_V1.value,),
        ).fetchall()

        ev_id_b = str(rows[0][0])
        ev_id_a = str(rows[1][0])

        # Outcome for A
        _insert_outcome(
            db,
            producer_id="producer-a",
            asset="BTC",
            horizon="24h",
            forecast_action="long",
            direction_correct=True,
            ts=ts,
        )
        # Fix the forecast_event_id to point to actual forecast
        db.conn.execute(
            "UPDATE events SET payload = json_set(payload, '$.forecast_event_id', ?) WHERE rowid = (SELECT MAX(rowid) FROM events WHERE type = ?)",
            (ev_id_a, EventType.FORECAST_OUTCOME_V1.value),
        )

        # Outcome for B
        _insert_outcome(
            db,
            producer_id="producer-b",
            asset="BTC",
            horizon="24h",
            forecast_action="long",
            direction_correct=True,
            ts=ts,
        )
        db.conn.execute(
            "UPDATE events SET payload = json_set(payload, '$.forecast_event_id', ?) WHERE rowid = (SELECT MAX(rowid) FROM events WHERE type = ?)",
            (ev_id_b, EventType.FORECAST_OUTCOME_V1.value),
        )

    db.conn.commit()

    agg = PerformanceAggregator(db)
    result = agg.compute()
    assert result["correlation_rows"] >= 1

    matrix = agg.get_correlation_matrix("BTC", "24h")
    assert matrix["pairs"]
    pair = matrix["pairs"][0]
    assert abs(pair["agreement_rate"] - 1.0) < 1e-9


def test_correlation_always_disagree(tmp_path) -> None:
    """Two producers always disagree → agreement_rate=0.0."""
    db = Database(tmp_path / "brain.db")

    now = datetime.now(tz=UTC)
    for i in range(10):
        ts = now - timedelta(hours=2 * i + 1)

        # Producer A: long
        db.append_event(
            event_type=EventType.FORECAST_V1,
            payload={
                "forecast_id": str(uuid.uuid4()),
                "asset": "BTC",
                "horizon": "24h",
                "action": "long",
                "confidence": 0.7,
                "source": "pa@1.0",
                "regime_tag": "unknown",
                "lifecycle_state": "new",
                "visible_signal_refs": [],
                "used_signal_refs": [],
            },
            source="pa",
            ts=ts,
        )
        rows = db.conn.execute(
            "SELECT id FROM events WHERE type = ? ORDER BY rowid DESC LIMIT 1",
            (EventType.FORECAST_V1.value,),
        ).fetchall()
        ev_id_a = str(rows[0][0])

        # Producer B: short
        db.append_event(
            event_type=EventType.FORECAST_V1,
            payload={
                "forecast_id": str(uuid.uuid4()),
                "asset": "BTC",
                "horizon": "24h",
                "action": "short",
                "confidence": 0.6,
                "source": "pb@1.0",
                "regime_tag": "unknown",
                "lifecycle_state": "new",
                "visible_signal_refs": [],
                "used_signal_refs": [],
            },
            source="pb",
            ts=ts,
        )
        rows = db.conn.execute(
            "SELECT id FROM events WHERE type = ? ORDER BY rowid DESC LIMIT 1",
            (EventType.FORECAST_V1.value,),
        ).fetchall()
        ev_id_b = str(rows[0][0])

        # Outcome A
        _insert_outcome(
            db,
            producer_id="pa",
            asset="BTC",
            horizon="24h",
            forecast_action="long",
            direction_correct=True,
            ts=ts,
        )
        db.conn.execute(
            "UPDATE events SET payload = json_set(payload, '$.forecast_event_id', ?) WHERE rowid = (SELECT MAX(rowid) FROM events WHERE type = ?)",
            (ev_id_a, EventType.FORECAST_OUTCOME_V1.value),
        )

        # Outcome B
        _insert_outcome(
            db,
            producer_id="pb",
            asset="BTC",
            horizon="24h",
            forecast_action="short",
            direction_correct=False,
            ts=ts,
        )
        db.conn.execute(
            "UPDATE events SET payload = json_set(payload, '$.forecast_event_id', ?) WHERE rowid = (SELECT MAX(rowid) FROM events WHERE type = ?)",
            (ev_id_b, EventType.FORECAST_OUTCOME_V1.value),
        )

    db.conn.commit()

    agg = PerformanceAggregator(db)
    agg.compute()

    matrix = agg.get_correlation_matrix("BTC", "24h")
    assert matrix["pairs"]
    pair = matrix["pairs"][0]
    assert abs(pair["agreement_rate"] - 0.0) < 1e-9


def test_get_producer_stats_reads_latest(tmp_path) -> None:
    """get_producer_stats → reads latest from producer_performance table."""
    db = Database(tmp_path / "brain.db")

    # Insert enough outcomes for stats
    for i in range(10):
        _insert_outcome(db, direction_correct=(i < 6))

    agg = PerformanceAggregator(db)
    agg.compute()

    stats = agg.get_producer_stats("tradfi-basis", "BTC", "24h", regime="all")
    assert stats is not None
    assert stats["forecast_count"] == 10
    assert abs(stats["win_rate"] - 0.6) < 1e-9
    assert stats["avg_brier"] is not None
    assert stats["avg_confidence"] is not None


def test_aggregator_never_raises(tmp_path) -> None:
    """compute() on corrupted data should not raise."""
    db = Database(tmp_path / "brain.db")

    # Insert a malformed outcome event
    db.append_event(
        event_type=EventType.FORECAST_OUTCOME_V1,
        payload={"broken": True},
        source="test",
    )

    agg = PerformanceAggregator(db)
    result = agg.compute()
    # Should return gracefully even with bad data
    assert isinstance(result, dict)
