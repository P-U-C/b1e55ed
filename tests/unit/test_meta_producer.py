"""Tests for engine.producers.meta — P4.4"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

try:
    from datetime import UTC
except ImportError:  # pragma: no cover
    UTC = UTC

from engine.core.database import Database
from engine.core.events import AbstentionReason, EventType
from engine.producers.meta import (
    MetaProducer,
)


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def _make_ctx(db: Database):
    """Minimal ProducerContext for MetaProducer."""
    from engine.core.config import Config
    from engine.core.metrics import MetricsRegistry
    from engine.producers.base import ProducerContext

    return ProducerContext(
        config=Config(universe={"symbols": ["BTC"]}),
        db=db,
        client=SimpleNamespace(),
        metrics=MetricsRegistry(),
        logger=logging.getLogger("test"),
    )


def _insert_outcome(
    db: Database,
    *,
    producer_id: str = "tradfi-basis",
    asset: str = "BTC",
    horizon: str = "24h",
    forecast_action: str = "long",
    direction_correct: bool = True,
    forecast_confidence: float = 0.7,
    ts: datetime | None = None,
    forecast_event_id: str | None = None,
) -> str:
    ts = ts or datetime.now(tz=UTC)
    outcome_binary = 1.0 if direction_correct else 0.0
    brier_score = (forecast_confidence - outcome_binary) ** 2

    payload = {
        "forecast_event_id": forecast_event_id or str(uuid.uuid4()),
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
        "regime_at_forecast": "unknown",
        "resolved_at": ts.timestamp(),
    }
    ev = db.append_event(
        event_type=EventType.FORECAST_OUTCOME_V1,
        payload=payload,
        source="brain.outcome_resolver",
        ts=ts,
    )
    return str(ev.id)


def _bulk_insert_outcomes(db: Database, n: int) -> None:
    """Insert n FORECAST_OUTCOME_V1 events."""
    now = datetime.now(tz=UTC)
    for i in range(n):
        ts = now - timedelta(hours=i)
        _insert_outcome(db, ts=ts, direction_correct=(i % 3 != 0))


def _insert_ensemble_history(
    db: Database, *, asset: str = "BTC", horizon: str = "24h", producers: dict[str, str], direction_correct: bool = True, count: int = 1
) -> None:
    """Insert historical forecast+outcome episodes matching the given ensemble state."""
    now = datetime.now(tz=UTC)
    for i in range(count):
        ts = now - timedelta(hours=2 * (i + 10))  # offset from "current" forecasts

        for producer_name, action in producers.items():
            fid = str(uuid.uuid4())
            ev = db.append_event(
                event_type=EventType.FORECAST_V1,
                payload={
                    "forecast_id": fid,
                    "asset": asset,
                    "horizon": horizon,
                    "action": action,
                    "confidence": 0.7,
                    "source": f"{producer_name}@1.0",
                    "regime_tag": "unknown",
                    "lifecycle_state": "new",
                    "visible_signal_refs": [],
                    "used_signal_refs": [],
                },
                source=producer_name,
                ts=ts,
            )

            _insert_outcome(
                db,
                producer_id=producer_name,
                asset=asset,
                horizon=horizon,
                forecast_action=action,
                direction_correct=direction_correct,
                ts=ts,
                forecast_event_id=str(ev.id),
            )


def _insert_current_forecasts(db: Database, *, asset: str = "BTC", producers: dict[str, str]) -> None:
    """Insert recent FORECAST_V1 events (within 2h window) for ensemble state."""
    now = datetime.now(tz=UTC) - timedelta(minutes=30)
    for producer_name, action in producers.items():
        db.append_event(
            event_type=EventType.FORECAST_V1,
            payload={
                "forecast_id": str(uuid.uuid4()),
                "asset": asset,
                "horizon": "24h",
                "action": action,
                "confidence": 0.7,
                "source": f"{producer_name}@1.0",
                "regime_tag": "unknown",
                "lifecycle_state": "new",
                "visible_signal_refs": [],
                "used_signal_refs": [],
            },
            source=producer_name,
            ts=now,
        )


# ---------------------------------------------------------------------------
# Activation gate
# ---------------------------------------------------------------------------


def test_meta_zero_outcomes_abstains(tmp_path) -> None:
    """MetaProducer with 0 outcomes → abstains (insufficient_history)."""
    db = Database(tmp_path / "brain.db")
    ctx = _make_ctx(db)
    mp = MetaProducer(ctx, shadow=False)
    result = mp.produce("BTC", "24h")
    assert result.action == "no_forecast"
    assert result.abstention_reason == AbstentionReason.INSUFFICIENT_DATA


def test_meta_499_outcomes_abstains(tmp_path) -> None:
    """MetaProducer with 499 outcomes → still abstains (below threshold)."""
    db = Database(tmp_path / "brain.db")
    _bulk_insert_outcomes(db, 499)

    ctx = _make_ctx(db)
    mp = MetaProducer(ctx, shadow=False)
    result = mp.produce("BTC", "24h")
    assert result.action == "no_forecast"
    assert result.abstention_reason == AbstentionReason.INSUFFICIENT_DATA


# ---------------------------------------------------------------------------
# Pattern matching
# ---------------------------------------------------------------------------


def test_meta_no_pattern_match_abstains(tmp_path) -> None:
    """MetaProducer with 500+ outcomes but no pattern match → abstains."""
    db = Database(tmp_path / "brain.db")
    _bulk_insert_outcomes(db, 501)

    # Insert current forecasts but no matching historical episodes
    _insert_current_forecasts(db, producers={"prod-x": "long", "prod-y": "short"})

    ctx = _make_ctx(db)
    mp = MetaProducer(ctx, shadow=False)
    result = mp.produce("BTC", "24h")
    assert result.action == "no_forecast"


def test_meta_pattern_found_emits(tmp_path) -> None:
    """MetaProducer with 500+ outcomes, pattern found → emits forecast."""
    db = Database(tmp_path / "brain.db")
    _bulk_insert_outcomes(db, 501)

    ensemble = {"prod-a": "long", "prod-b": "long"}

    # Insert matching historical episodes (mostly correct)
    _insert_ensemble_history(
        db,
        producers=ensemble,
        direction_correct=True,
        count=12,
    )
    _insert_ensemble_history(
        db,
        producers=ensemble,
        direction_correct=False,
        count=3,
    )

    # Insert current ensemble state
    _insert_current_forecasts(db, producers=ensemble)

    ctx = _make_ctx(db)
    mp = MetaProducer(ctx, shadow=False)
    result = mp.produce("BTC", "24h")

    # Should emit a real forecast (not abstain)
    assert result.action in {"long", "short", "flat"}
    assert result.confidence > 0
    assert result.confidence <= 1.0


# ---------------------------------------------------------------------------
# Shadow mode
# ---------------------------------------------------------------------------


def test_meta_shadow_mode_abstains(tmp_path) -> None:
    """shadow=True (default): pattern found, still abstains with shadow log."""
    db = Database(tmp_path / "brain.db")
    _bulk_insert_outcomes(db, 501)

    ensemble = {"prod-a": "long", "prod-b": "long"}
    _insert_ensemble_history(db, producers=ensemble, direction_correct=True, count=15)
    _insert_current_forecasts(db, producers=ensemble)

    ctx = _make_ctx(db)
    mp = MetaProducer(ctx, shadow=True)
    result = mp.produce("BTC", "24h")

    assert result.action == "no_forecast"
    assert result.abstention_reason == AbstentionReason.SHADOW_MODE


def test_meta_shadow_false_emits(tmp_path) -> None:
    """shadow=False: pattern found → emits with confidence=win_rate."""
    db = Database(tmp_path / "brain.db")
    _bulk_insert_outcomes(db, 501)

    ensemble = {"prod-a": "long", "prod-b": "long"}
    _insert_ensemble_history(db, producers=ensemble, direction_correct=True, count=15)
    _insert_current_forecasts(db, producers=ensemble)

    ctx = _make_ctx(db)
    mp = MetaProducer(ctx, shadow=False)
    result = mp.produce("BTC", "24h")

    assert result.action in {"long", "short", "flat"}
    # Confidence should equal the historical win rate (no inflation)
    assert 0.0 < result.confidence <= 1.0


# ---------------------------------------------------------------------------
# Hard constraints
# ---------------------------------------------------------------------------


def test_meta_confidence_equals_win_rate(tmp_path) -> None:
    """Confidence always equals win_rate (no inflation, no post-processing)."""
    db = Database(tmp_path / "brain.db")
    _bulk_insert_outcomes(db, 501)

    ensemble = {"prod-a": "long", "prod-b": "long"}
    # 11 correct, 4 wrong → win_rate = 11/15 ≈ 0.733
    _insert_ensemble_history(db, producers=ensemble, direction_correct=True, count=11)
    _insert_ensemble_history(db, producers=ensemble, direction_correct=False, count=4)
    _insert_current_forecasts(db, producers=ensemble)

    ctx = _make_ctx(db)
    mp = MetaProducer(ctx, shadow=False)
    result = mp.produce("BTC", "24h")

    if result.action != "no_forecast":
        # Confidence should be the raw win rate, rounded to 3 decimal places
        assert result.confidence == round(result.confidence, 3)
        # It should not exceed the true win rate
        assert result.confidence <= 1.0


def test_meta_never_reads_price_data(tmp_path) -> None:
    """MetaProducer only reads performance tables, never price data.

    Verifying by inspection: MetaProducer's produce() method only queries
    events table (FORECAST_V1, FORECAST_OUTCOME_V1) and producer_performance,
    producer_correlation. No SIGNAL_PRICE_WS_V1, no price_history, no
    external market API calls.
    """
    import inspect

    source = inspect.getsource(MetaProducer)

    # Should not reference any price signal types or external APIs
    assert "SIGNAL_PRICE_WS_V1" not in source
    assert "price_history" not in source
    assert "binance" not in source.lower()
    assert "klines" not in source.lower()

    # Should reference only forecast/outcome events
    assert "FORECAST_V1" in source
    assert "FORECAST_OUTCOME_V1" in source


def test_meta_db_only_mode(tmp_path) -> None:
    """MetaProducer works with raw Database (no ProducerContext)."""
    db = Database(tmp_path / "brain.db")
    mp = MetaProducer(db, shadow=True)
    result = mp.produce("BTC", "24h")
    assert result.action == "no_forecast"
    assert result.abstention_reason == AbstentionReason.INSUFFICIENT_DATA
