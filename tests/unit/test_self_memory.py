from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any

import pytest

from engine.core.events import AbstentionReason, ForecastLifecycleState, ForecastPayload
from engine.core.forecast import make_forecast_id
from engine.core.interpreter import Interpreter, NullInterpreter, SelfMemoryInterpreter
from engine.core.self_memory import MAX_DELTA, SelfMemory, SelfMemoryConfig, _brier_to_delta

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017


@pytest.fixture()
def memory_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE forecast_calibration (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            forecast_id TEXT NOT NULL UNIQUE,
            producer_name TEXT NOT NULL,
            asset TEXT NOT NULL,
            regime TEXT NOT NULL DEFAULT 'unknown',
            horizon TEXT NOT NULL,
            direction TEXT NOT NULL,
            confidence REAL NOT NULL,
            calibrated INTEGER NOT NULL DEFAULT 0,
            outcome REAL,
            brier_score REAL,
            price_at_emit REAL,
            price_at_resolve REAL,
            emitted_at TEXT NOT NULL,
            resolved_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    try:
        yield conn
    finally:
        conn.close()


def _ts(days_ago: int, offset_minutes: int) -> str:
    return (datetime.now(tz=UTC) - timedelta(days=days_ago, minutes=offset_minutes)).isoformat()


def _seed_resolved(
    conn: sqlite3.Connection,
    *,
    prefix: str,
    producer: str,
    regime: str,
    brier: float,
    count: int,
    days_ago: int,
    confidence: float = 0.6,
) -> None:
    for i in range(count):
        conn.execute(
            """
            INSERT INTO forecast_calibration
                (forecast_id, producer_name, asset, regime, horizon, direction,
                 confidence, outcome, brier_score, emitted_at, resolved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{prefix}-{i}",
                producer,
                "BTC",
                regime,
                "4h",
                "bullish",
                confidence,
                1.0,
                brier,
                _ts(days_ago + 1, i),
                _ts(days_ago, i),
            ),
        )
    conn.commit()


class _StaticInterpreter(Interpreter):
    producer_name = "unit-producer"
    producer_version = "1.0.0"

    def __init__(self, payload: ForecastPayload) -> None:
        self.payload = payload

    def interpret(
        self,
        *,
        asset: str,
        horizon: str,
        signals: list[dict[str, Any]],
        regime_tag: str = "unknown",
        visible_signal_refs: list[str] | None = None,
    ) -> ForecastPayload:
        return self.payload.model_copy(deep=True)


def _mk_payload(*, action: str = "long", confidence: float = 0.6) -> ForecastPayload:
    kwargs: dict[str, Any] = {
        "forecast_id": make_forecast_id(),
        "asset": "BTC",
        "horizon": "4h",
        "action": action,
        "confidence": confidence,
        "source": "unit-producer@1.0.0",
        "regime_tag": "unknown",
        "lifecycle_state": ForecastLifecycleState.NEW,
        "visible_signal_refs": ["evt-1"],
        "used_signal_refs": ["evt-1"],
    }
    if action == "no_forecast":
        kwargs["confidence"] = 0.0
        kwargs["abstention_reason"] = AbstentionReason.INSUFFICIENT_DATA
    return ForecastPayload(**kwargs)


def test_brier_to_delta_excellent() -> None:
    assert _brier_to_delta(0.05) == pytest.approx(0.15)


def test_brier_to_delta_random_baseline() -> None:
    assert _brier_to_delta(0.25) == pytest.approx(0.0)


def test_brier_to_delta_poor() -> None:
    assert _brier_to_delta(0.40) == pytest.approx(-0.20)


def test_self_memory_query_empty_db_returns_not_applied(memory_db: sqlite3.Connection) -> None:
    result = SelfMemory(memory_db).query(producer_name="unit-producer", asset="BTC", regime="BULL")

    assert result.applied is False
    assert result.resolved_count == 0
    assert result.confidence_delta == pytest.approx(0.0)


def test_self_memory_query_good_history_returns_positive_delta(memory_db: sqlite3.Connection) -> None:
    _seed_resolved(
        memory_db,
        prefix="good",
        producer="unit-producer",
        regime="BULL",
        brier=0.15,
        count=10,
        days_ago=1,
    )

    result = SelfMemory(memory_db).query(producer_name="unit-producer", asset="BTC", regime="BULL")

    assert result.applied is True
    assert result.resolved_count == 10
    assert result.confidence_delta > 0.0


def test_self_memory_query_poor_history_returns_negative_delta(memory_db: sqlite3.Connection) -> None:
    _seed_resolved(
        memory_db,
        prefix="poor",
        producer="unit-producer",
        regime="BULL",
        brier=0.35,
        count=10,
        days_ago=1,
    )

    result = SelfMemory(memory_db).query(producer_name="unit-producer", asset="BTC", regime="BULL")

    assert result.applied is True
    assert result.resolved_count == 10
    assert result.confidence_delta < 0.0


def test_self_memory_query_recent_poor_streak_overrides_long_term(memory_db: sqlite3.Connection) -> None:
    _seed_resolved(
        memory_db,
        prefix="long-good",
        producer="unit-producer",
        regime="BULL",
        brier=0.15,
        count=8,
        days_ago=30,
    )
    _seed_resolved(
        memory_db,
        prefix="recent-poor",
        producer="unit-producer",
        regime="BULL",
        brier=0.40,
        count=2,
        days_ago=1,
    )

    result = SelfMemory(memory_db).query(producer_name="unit-producer", asset="BTC", regime="UNKNOWN")

    assert result.applied is True
    assert result.resolved_count == 10
    assert result.confidence_delta < 0.0


def test_self_memory_query_caps_positive_delta_at_max(monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection) -> None:
    _seed_resolved(
        memory_db,
        prefix="cap-pos",
        producer="unit-producer",
        regime="BULL",
        brier=0.15,
        count=10,
        days_ago=1,
    )
    monkeypatch.setattr("engine.core.self_memory._brier_to_delta", lambda _brier: 2.0)

    result = SelfMemory(memory_db, config=SelfMemoryConfig(max_delta=MAX_DELTA)).query(
        producer_name="unit-producer",
        asset="BTC",
        regime="BULL",
    )

    assert result.applied is True
    assert result.confidence_delta == pytest.approx(MAX_DELTA)


def test_self_memory_query_caps_negative_delta_at_max(monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection) -> None:
    _seed_resolved(
        memory_db,
        prefix="cap-neg",
        producer="unit-producer",
        regime="BULL",
        brier=0.15,
        count=10,
        days_ago=1,
    )
    monkeypatch.setattr("engine.core.self_memory._brier_to_delta", lambda _brier: -2.0)

    result = SelfMemory(memory_db, config=SelfMemoryConfig(max_delta=MAX_DELTA)).query(
        producer_name="unit-producer",
        asset="BTC",
        regime="BULL",
    )

    assert result.applied is True
    assert result.confidence_delta == pytest.approx(-MAX_DELTA)


def test_self_memory_interpreter_with_no_db_passes_through_unchanged() -> None:
    candidate = _mk_payload(action="long", confidence=0.61)
    wrapped = SelfMemoryInterpreter(inner=_StaticInterpreter(candidate), db=None)

    out = wrapped.interpret(asset="BTC", horizon="4h", signals=[], regime_tag="BULL")

    assert out.action == candidate.action
    assert out.confidence == pytest.approx(candidate.confidence)


def test_self_memory_interpreter_wrapping_null_interpreter_preserves_abstention(memory_db: sqlite3.Connection) -> None:
    wrapped = SelfMemoryInterpreter(inner=NullInterpreter(), db=memory_db)
    wrapped.producer_name = "unit-producer"
    wrapped.producer_version = "1.0.0"

    out = wrapped.interpret(asset="BTC", horizon="4h", signals=[], regime_tag="BULL")

    assert out.action == "no_forecast"
    assert out.abstention_reason == AbstentionReason.INSUFFICIENT_DATA


def test_self_memory_interpreter_boosts_confidence_for_good_track_record(memory_db: sqlite3.Connection) -> None:
    _seed_resolved(
        memory_db,
        prefix="interp-good",
        producer="unit-producer",
        regime="BULL",
        brier=0.15,
        count=10,
        days_ago=1,
    )
    candidate = _mk_payload(action="long", confidence=0.50)
    wrapped = SelfMemoryInterpreter(inner=_StaticInterpreter(candidate), db=memory_db)

    out = wrapped.interpret(asset="BTC", horizon="4h", signals=[], regime_tag="BULL")

    assert out.action == "long"
    assert out.confidence > candidate.confidence


def test_self_memory_interpreter_suppresses_confidence_for_poor_track_record(memory_db: sqlite3.Connection) -> None:
    _seed_resolved(
        memory_db,
        prefix="interp-poor",
        producer="unit-producer",
        regime="BULL",
        brier=0.35,
        count=10,
        days_ago=1,
    )
    candidate = _mk_payload(action="long", confidence=0.65)
    wrapped = SelfMemoryInterpreter(inner=_StaticInterpreter(candidate), db=memory_db)

    out = wrapped.interpret(asset="BTC", horizon="4h", signals=[], regime_tag="BULL")

    assert out.action == "long"
    assert out.confidence < candidate.confidence


def test_self_memory_interpreter_regime_specific_worse_performance_adds_suppression(memory_db: sqlite3.Connection) -> None:
    # Overall mean ~= 0.24 (neutral), BULL regime good, BEAR regime poor.
    _seed_resolved(
        memory_db,
        prefix="mix-bull",
        producer="unit-producer",
        regime="BULL",
        brier=0.15,
        count=7,
        days_ago=10,
    )
    _seed_resolved(
        memory_db,
        prefix="mix-bear",
        producer="unit-producer",
        regime="BEAR",
        brier=0.45,
        count=3,
        days_ago=10,
    )

    candidate = _mk_payload(action="long", confidence=0.70)
    wrapped = SelfMemoryInterpreter(inner=_StaticInterpreter(candidate), db=memory_db)

    out_bull = wrapped.interpret(asset="BTC", horizon="4h", signals=[], regime_tag="BULL")
    out_bear = wrapped.interpret(asset="BTC", horizon="4h", signals=[], regime_tag="BEAR")

    assert out_bear.action == "long"
    assert out_bull.action == "long"
    assert out_bear.confidence < out_bull.confidence
    assert out_bear.confidence < candidate.confidence
