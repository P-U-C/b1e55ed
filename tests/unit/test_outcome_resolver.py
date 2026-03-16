"""Tests for engine.brain.outcome_resolver — P4.4"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

try:
    from datetime import UTC
except ImportError:  # pragma: no cover

    UTC = UTC

from engine.brain.outcome_resolver import OutcomeResolver, _parse_horizon_seconds
from engine.core.database import Database
from engine.core.events import EventType


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def _insert_forecast(
    db: Database,
    *,
    asset: str = "BTC",
    action: str = "long",
    confidence: float = 0.7,
    horizon: str = "4h",
    ts: datetime | None = None,
    regime_tag: str = "unknown",
) -> str:
    ts = ts or datetime.now(tz=UTC)
    forecast_id = str(uuid.uuid4())
    payload = {
        "forecast_id": forecast_id,
        "protocol_version": "1.0",
        "asset": asset,
        "horizon": horizon,
        "action": action,
        "confidence": confidence,
        "calibrated": False,
        "invalidation": None,
        "regime_tag": regime_tag,
        "crisis_state": False,
        "reasoning_hash": None,
        "source": "test-producer@1.0",
        "lifecycle_state": "new",
        "supersedes_forecast_id": None,
        "visible_signal_refs": [],
        "used_signal_refs": [],
        "abstention_reason": None,
    }
    ev = db.append_event(
        event_type=EventType.FORECAST_V1,
        payload=payload,
        source="test-producer",
        ts=ts,
    )
    return str(ev.id)


# ---------------------------------------------------------------------------
# Horizon parsing
# ---------------------------------------------------------------------------


def test_parse_horizon_seconds() -> None:
    assert _parse_horizon_seconds("4h") == 4 * 3600
    assert _parse_horizon_seconds("24h") == 24 * 3600
    assert _parse_horizon_seconds("3d") == 3 * 86400
    assert _parse_horizon_seconds("7d") == 7 * 86400
    assert _parse_horizon_seconds("15m") == 15 * 60
    assert _parse_horizon_seconds("invalid") is None


# ---------------------------------------------------------------------------
# Core resolver tests
# ---------------------------------------------------------------------------


def test_resolver_no_forecasts(tmp_path) -> None:
    """Resolver with no FORECAST_V1 events → resolves 0, no error."""
    db = Database(tmp_path / "brain.db")
    resolver = OutcomeResolver(db)
    assert resolver.resolve_pending() == 0


def test_resolver_resolves_elapsed_forecast(tmp_path) -> None:
    """Resolver with 1 unresolved FORECAST_V1 (horizon elapsed) → resolves it."""
    db = Database(tmp_path / "brain.db")

    # Insert a forecast from 5 hours ago with a 4h horizon
    ts = datetime.now(tz=UTC) - timedelta(hours=5)
    event_id = _insert_forecast(db, ts=ts, horizon="4h", action="long", confidence=0.7)

    # Mock Binance: first call = forecast price (100), second call = actual price (105)
    call_count = {"n": 0}

    def _mock_get(*args, **kwargs):
        call_count["n"] += 1
        close = "100.0" if call_count["n"] == 1 else "105.0"
        return type(
            "R",
            (),
            {
                "status_code": 200,
                "raise_for_status": lambda self: None,
                "json": lambda self: [[0, "100.0", "110.0", "99.0", close, "1000"]],
            },
        )()

    with patch("engine.brain.outcome_resolver.httpx.get", side_effect=_mock_get):
        resolver = OutcomeResolver(db)
        count = resolver.resolve_pending()

    assert count == 1

    # Verify FORECAST_OUTCOME_V1 event was written
    outcome_events = db.get_events(event_type=EventType.FORECAST_OUTCOME_V1, limit=10)
    assert len(outcome_events) == 1
    payload = outcome_events[0].payload
    assert payload["forecast_event_id"] == event_id
    assert payload["asset"] == "BTC"
    assert payload["horizon"] == "4h"
    assert payload["forecast_action"] == "long"

    # Verify resolution state
    row = db.conn.execute(
        "SELECT forecast_event_id, outcome_event_id FROM forecast_resolution_state WHERE forecast_event_id = ?",
        (event_id,),
    ).fetchone()
    assert row is not None


def test_resolver_skips_not_elapsed(tmp_path) -> None:
    """Resolver with 1 unresolved FORECAST_V1 (horizon NOT yet elapsed) → skips it."""
    db = Database(tmp_path / "brain.db")

    # Insert a forecast from 1 hour ago with a 4h horizon
    ts = datetime.now(tz=UTC) - timedelta(hours=1)
    _insert_forecast(db, ts=ts, horizon="4h")

    resolver = OutcomeResolver(db)
    assert resolver.resolve_pending() == 0


def test_resolver_idempotent(tmp_path) -> None:
    """Resolver called twice on same forecast → resolves only once."""
    db = Database(tmp_path / "brain.db")

    ts = datetime.now(tz=UTC) - timedelta(hours=5)
    _insert_forecast(db, ts=ts, horizon="4h")

    call_count = {"n": 0}

    def _mock_get(*args, **kwargs):
        call_count["n"] += 1
        close = "100.0" if call_count["n"] % 2 == 1 else "105.0"
        return type(
            "R",
            (),
            {
                "status_code": 200,
                "raise_for_status": lambda self: None,
                "json": lambda self: [[0, "100.0", "110.0", "99.0", close, "1000"]],
            },
        )()

    with patch("engine.brain.outcome_resolver.httpx.get", side_effect=_mock_get):
        resolver = OutcomeResolver(db)
        first = resolver.resolve_pending()
        second = resolver.resolve_pending()

    assert first == 1
    assert second == 0

    # Only one outcome event should exist
    outcome_events = db.get_events(event_type=EventType.FORECAST_OUTCOME_V1, limit=10)
    assert len(outcome_events) == 1


def test_resolver_binance_fallback(tmp_path) -> None:
    """Price fetch fallback: no price_history → calls Binance mock → succeeds."""
    db = Database(tmp_path / "brain.db")

    ts = datetime.now(tz=UTC) - timedelta(hours=25)
    _insert_forecast(db, ts=ts, horizon="24h", action="short", confidence=0.8)

    # Binance: first call = forecast price (100), second call = actual price (92, went down → short correct)
    call_count = {"n": 0}

    def _mock_get(*args, **kwargs):
        call_count["n"] += 1
        close = "100.0" if call_count["n"] == 1 else "92.0"
        return type(
            "R",
            (),
            {
                "status_code": 200,
                "raise_for_status": lambda self: None,
                "json": lambda self: [[0, "100.0", "105.0", "90.0", close, "1000"]],
            },
        )()

    with patch("engine.brain.outcome_resolver.httpx.get", side_effect=_mock_get):
        resolver = OutcomeResolver(db)
        count = resolver.resolve_pending()

    assert count == 1

    outcome_events = db.get_events(event_type=EventType.FORECAST_OUTCOME_V1, limit=10)
    assert len(outcome_events) == 1
    payload = outcome_events[0].payload
    assert payload["forecast_action"] == "short"
    assert payload["direction_correct"] is True


def test_resolver_both_fetch_fail_skips(tmp_path) -> None:
    """Price fetch fails both ways → skips forecast, returns 0."""
    db = Database(tmp_path / "brain.db")

    ts = datetime.now(tz=UTC) - timedelta(hours=5)
    _insert_forecast(db, ts=ts, horizon="4h")

    with patch("engine.brain.outcome_resolver.httpx.get", side_effect=Exception("network")):
        resolver = OutcomeResolver(db)
        count = resolver.resolve_pending()

    assert count == 0
    assert resolver.last_skipped_missing_price > 0


def test_brier_score_long_correct(tmp_path) -> None:
    """action=long, price went up → direction_correct=True, brier=(confidence-1)^2."""
    db = Database(tmp_path / "brain.db")

    ts = datetime.now(tz=UTC) - timedelta(hours=5)
    _insert_forecast(db, ts=ts, horizon="4h", action="long", confidence=0.7)

    # First call = forecast price (100), second = actual price (105, up → long correct)
    call_count = {"n": 0}

    def _mock_get(*args, **kwargs):
        call_count["n"] += 1
        close = "100.0" if call_count["n"] == 1 else "105.0"
        return type(
            "R",
            (),
            {
                "status_code": 200,
                "raise_for_status": lambda self: None,
                "json": lambda self: [[0, "100.0", "110.0", "99.0", close, "1000"]],
            },
        )()

    with patch("engine.brain.outcome_resolver.httpx.get", side_effect=_mock_get):
        resolver = OutcomeResolver(db)
        resolver.resolve_pending()

    outcome_events = db.get_events(event_type=EventType.FORECAST_OUTCOME_V1, limit=10)
    assert len(outcome_events) == 1
    payload = outcome_events[0].payload
    assert payload["direction_correct"] is True
    assert abs(payload["brier_score"] - (0.7 - 1.0) ** 2) < 1e-9


def test_brier_score_long_incorrect(tmp_path) -> None:
    """action=long, price went down → direction_correct=False, brier=(confidence-0)^2."""
    db = Database(tmp_path / "brain.db")

    ts = datetime.now(tz=UTC) - timedelta(hours=5)
    _insert_forecast(db, ts=ts, horizon="4h", action="long", confidence=0.7)

    # First call = forecast price (100), second = actual price (95, down → long incorrect)
    call_count = {"n": 0}

    def _mock_get(*args, **kwargs):
        call_count["n"] += 1
        close = "100.0" if call_count["n"] == 1 else "95.0"
        return type(
            "R",
            (),
            {
                "status_code": 200,
                "raise_for_status": lambda self: None,
                "json": lambda self: [[0, "100.0", "100.0", "90.0", close, "1000"]],
            },
        )()

    with patch("engine.brain.outcome_resolver.httpx.get", side_effect=_mock_get):
        resolver = OutcomeResolver(db)
        resolver.resolve_pending()

    outcome_events = db.get_events(event_type=EventType.FORECAST_OUTCOME_V1, limit=10)
    assert len(outcome_events) == 1
    payload = outcome_events[0].payload
    assert payload["direction_correct"] is False
    assert abs(payload["brier_score"] - (0.7 - 0.0) ** 2) < 1e-9


def test_resolver_skips_no_forecast_action(tmp_path) -> None:
    """Forecasts with action=no_forecast are ignored."""
    db = Database(tmp_path / "brain.db")

    ts = datetime.now(tz=UTC) - timedelta(hours=5)
    payload = {
        "forecast_id": str(uuid.uuid4()),
        "protocol_version": "1.0",
        "asset": "BTC",
        "horizon": "4h",
        "action": "no_forecast",
        "confidence": 0.0,
        "source": "test@1.0",
        "regime_tag": "unknown",
        "lifecycle_state": "new",
        "abstention_reason": "insufficient_data",
        "visible_signal_refs": [],
        "used_signal_refs": [],
    }
    db.append_event(
        event_type=EventType.FORECAST_V1,
        payload=payload,
        source="test",
        ts=ts,
    )

    resolver = OutcomeResolver(db)
    assert resolver.resolve_pending() == 0
