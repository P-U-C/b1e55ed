from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest

from engine.brain.conviction_state import ConvictionStateReader
from engine.core.events import AbstentionReason, EventType, ForecastLifecycleState, ForecastPayload
from engine.core.forecast import make_forecast_id
from engine.core.interpreter import Interpreter, NoveltyInterpreter
from engine.core.novelty import compute_novelty_penalty

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017


class _ConnDB:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn


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


class _BrokenConn:
    def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        raise sqlite3.OperationalError("boom")


class _BrokenDB:
    def __init__(self) -> None:
        self.conn = _BrokenConn()


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


def _insert_forecast(
    conn: sqlite3.Connection,
    *,
    asset: str,
    action: str,
    confidence: float,
    minutes_ago: int = 0,
) -> None:
    ts = (datetime.now(tz=UTC) - timedelta(minutes=minutes_ago)).isoformat()
    payload = {
        "forecast_id": str(uuid.uuid4()),
        "asset": asset,
        "horizon": "4h",
        "action": action,
        "confidence": confidence,
        "source": "seed@1.0.0",
        "lifecycle_state": "new",
        "visible_signal_refs": [],
        "used_signal_refs": [],
    }
    conn.execute(
        "INSERT INTO events (id, type, ts, payload) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), EventType.FORECAST_V1.value, ts, json.dumps(payload)),
    )
    conn.commit()


@pytest.fixture()
def forecast_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE events (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            ts TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """
    )
    try:
        yield conn
    finally:
        conn.close()


def test_conviction_state_reader_empty_db_returns_neutral(forecast_conn: sqlite3.Connection) -> None:
    state = ConvictionStateReader(_ConnDB(forecast_conn)).get("BTC")

    assert state.conviction == pytest.approx(0.0)
    assert state.forecast_count == 0


def test_conviction_state_reader_long_only_is_positive(forecast_conn: sqlite3.Connection) -> None:
    for _ in range(3):
        _insert_forecast(forecast_conn, asset="BTC", action="long", confidence=0.7)

    state = ConvictionStateReader(_ConnDB(forecast_conn)).get("BTC")

    assert state.forecast_count == 3
    assert state.conviction > 0


def test_conviction_state_reader_mixed_long_short_near_zero(forecast_conn: sqlite3.Connection) -> None:
    _insert_forecast(forecast_conn, asset="BTC", action="long", confidence=0.7)
    _insert_forecast(forecast_conn, asset="BTC", action="short", confidence=0.7)
    _insert_forecast(forecast_conn, asset="BTC", action="long", confidence=0.3)
    _insert_forecast(forecast_conn, asset="BTC", action="short", confidence=0.3)

    state = ConvictionStateReader(_ConnDB(forecast_conn)).get("BTC")

    assert state.forecast_count == 4
    assert abs(state.conviction) < 0.05


def test_conviction_state_reader_db_error_returns_neutral() -> None:
    state = ConvictionStateReader(_BrokenDB()).get("BTC")

    assert state.conviction == pytest.approx(0.0)
    assert state.forecast_count == 0


def test_compute_novelty_penalty_agreement_suppresses_confidence() -> None:
    result = compute_novelty_penalty(
        candidate_action="long",
        candidate_confidence=0.7,
        brain_conviction=0.8,
    )

    assert result.applied is True
    assert result.confidence_delta < 0


def test_compute_novelty_penalty_contrarian_boosts_confidence() -> None:
    result = compute_novelty_penalty(
        candidate_action="short",
        candidate_confidence=0.7,
        brain_conviction=0.8,
    )

    assert result.applied is True
    assert result.confidence_delta > 0


def test_compute_novelty_penalty_weak_conviction_no_penalty() -> None:
    result = compute_novelty_penalty(
        candidate_action="long",
        candidate_confidence=0.7,
        brain_conviction=0.3,
    )

    assert result.applied is False
    assert result.confidence_delta == pytest.approx(0.0)


def test_compute_novelty_penalty_abstention_passes_through() -> None:
    result = compute_novelty_penalty(
        candidate_action="no_forecast",
        candidate_confidence=0.0,
        brain_conviction=0.8,
    )

    assert result.applied is False
    assert result.confidence_delta == pytest.approx(0.0)


def test_novelty_interpreter_shadow_mode_keeps_candidate_unchanged(forecast_conn: sqlite3.Connection) -> None:
    for _ in range(3):
        _insert_forecast(forecast_conn, asset="BTC", action="long", confidence=0.7)

    candidate = _mk_payload(action="long", confidence=0.6)
    wrapped = NoveltyInterpreter(inner=_StaticInterpreter(candidate), db=_ConnDB(forecast_conn), shadow=True)

    out = wrapped.interpret(asset="BTC", horizon="4h", signals=[], regime_tag="BULL")

    assert out.action == "long"
    assert out.confidence == pytest.approx(candidate.confidence)


def test_novelty_interpreter_live_mode_suppresses_confidence_for_low_novelty(forecast_conn: sqlite3.Connection) -> None:
    for _ in range(3):
        _insert_forecast(forecast_conn, asset="BTC", action="long", confidence=0.7)

    candidate = _mk_payload(action="long", confidence=0.6)
    wrapped = NoveltyInterpreter(inner=_StaticInterpreter(candidate), db=_ConnDB(forecast_conn), shadow=False)

    out = wrapped.interpret(asset="BTC", horizon="4h", signals=[], regime_tag="BULL")

    assert out.action == "long"
    assert out.confidence < candidate.confidence


def test_novelty_interpreter_live_mode_boosts_contrarian_signal(forecast_conn: sqlite3.Connection) -> None:
    for _ in range(3):
        _insert_forecast(forecast_conn, asset="BTC", action="long", confidence=0.7)

    candidate = _mk_payload(action="short", confidence=0.6)
    wrapped = NoveltyInterpreter(inner=_StaticInterpreter(candidate), db=_ConnDB(forecast_conn), shadow=False)

    out = wrapped.interpret(asset="BTC", horizon="4h", signals=[], regime_tag="BULL")

    assert out.action == "short"
    assert out.confidence > candidate.confidence


def test_novelty_interpreter_without_db_is_passthrough() -> None:
    candidate = _mk_payload(action="long", confidence=0.61)
    wrapped = NoveltyInterpreter(inner=_StaticInterpreter(candidate), db=None, shadow=False)

    out = wrapped.interpret(asset="BTC", horizon="4h", signals=[], regime_tag="BULL")

    assert out.action == candidate.action
    assert out.confidence == pytest.approx(candidate.confidence)


@pytest.mark.parametrize("action", ["long", "short"])
def test_novelty_interpreter_preserves_action_identity(action: str, forecast_conn: sqlite3.Connection) -> None:
    for _ in range(3):
        _insert_forecast(forecast_conn, asset="BTC", action="long", confidence=0.7)

    candidate = _mk_payload(action=action, confidence=0.9)
    wrapped = NoveltyInterpreter(inner=_StaticInterpreter(candidate), db=_ConnDB(forecast_conn), shadow=False)

    out = wrapped.interpret(asset="BTC", horizon="4h", signals=[], regime_tag="BULL")

    assert out.action == action
