from __future__ import annotations

import logging
from typing import Any

from engine.core.client import DataClient
from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import AbstentionReason, EventType, ForecastPayload
from engine.core.forecast import make_forecast_id
from engine.core.interpreter import Interpreter, NullInterpreter
from engine.core.metrics import MetricsRegistry
from engine.producers.base import BaseProducer, ProducerContext


class _RaisingInterpreter(Interpreter):
    def interpret(
        self,
        *,
        asset: str,
        horizon: str,
        signals: list[dict[str, Any]],
        regime_tag: str = "unknown",
        visible_signal_refs: list[str] | None = None,
    ) -> ForecastPayload:
        raise RuntimeError("boom")


class _LongInterpreter(Interpreter):
    def interpret(
        self,
        *,
        asset: str,
        horizon: str,
        signals: list[dict[str, Any]],
        regime_tag: str = "unknown",
        visible_signal_refs: list[str] | None = None,
    ) -> ForecastPayload:
        return ForecastPayload(
            forecast_id=make_forecast_id(),
            asset=asset,
            horizon=horizon,
            action="long",
            confidence=0.8,
            source=self.source,
            regime_tag=regime_tag,
            visible_signal_refs=visible_signal_refs or [],
            used_signal_refs=["sig-1"] if signals else [],
        )


class _TestProducer(BaseProducer):
    name = "test-producer"
    domain = "events"
    schedule = "continuous"

    def collect(self) -> list[dict]:
        return []

    def normalize(self, raw: list[dict]):  # type: ignore[no-untyped-def]
        return []


def _make_ctx(tmp_path) -> ProducerContext:
    db = Database(tmp_path / "events.db")
    return ProducerContext(
        config=Config(),
        db=db,
        client=DataClient(),
        metrics=MetricsRegistry(),
        logger=logging.getLogger("test"),
    )


def test_null_interpreter_interpret_returns_no_forecast() -> None:
    payload = NullInterpreter().interpret(asset="BTC", horizon="4h", signals=[])
    assert isinstance(payload, ForecastPayload)
    assert payload.action == "no_forecast"


def test_null_interpreter_interpret_sets_insufficient_data_reason() -> None:
    payload = NullInterpreter().interpret(asset="BTC", horizon="4h", signals=[])
    assert payload.abstention_reason == AbstentionReason.INSUFFICIENT_DATA


def test_safe_interpret_catches_exceptions_and_abstains() -> None:
    payload = _RaisingInterpreter().safe_interpret(asset="BTC", horizon="4h", signals=[])
    assert payload.action == "no_forecast"
    assert payload.abstention_reason == AbstentionReason.INSUFFICIENT_DATA


def test_safe_interpret_uses_default_reason_when_falling_back() -> None:
    payload = _RaisingInterpreter().safe_interpret(
        asset="BTC",
        horizon="4h",
        signals=[],
        default_reason=AbstentionReason.REGIME_MISMATCH,
    )
    assert payload.abstention_reason == AbstentionReason.REGIME_MISMATCH


def test_concrete_interpreter_can_return_long_forecast() -> None:
    interpreter = _LongInterpreter()
    interpreter.producer_name = "alpha"
    interpreter.producer_version = "1.2.3"

    payload = interpreter.safe_interpret(
        asset="ETH",
        horizon="24h",
        signals=[{"id": "sig-1"}],
        regime_tag="risk-on",
        visible_signal_refs=["evt-1"],
    )

    assert payload.action == "long"
    assert payload.source == "alpha@1.2.3"
    assert payload.visible_signal_refs == ["evt-1"]


def test_emit_forecast_returns_none_when_interpreter_is_none(tmp_path) -> None:
    producer = _TestProducer(_make_ctx(tmp_path))
    producer.interpreter = None

    forecast = producer.emit_forecast(asset="BTC", horizon="4h")

    assert forecast is None
    assert producer.ctx.db.get_events(event_type=EventType.FORECAST_V1, source=producer.name, limit=10) == []


def test_emit_forecast_returns_payload_when_interpreter_is_set(tmp_path) -> None:
    producer = _TestProducer(_make_ctx(tmp_path))
    producer.interpreter = NullInterpreter()

    forecast = producer.emit_forecast(asset="BTC", horizon="4h", signals=[{"x": 1}])

    assert isinstance(forecast, ForecastPayload)
    assert forecast.action == "no_forecast"


def test_emit_forecast_publishes_forecast_v1_event(tmp_path) -> None:
    producer = _TestProducer(_make_ctx(tmp_path))
    producer.interpreter = _LongInterpreter()

    forecast = producer.emit_forecast(asset="BTC", horizon="4h", signals=[{"signal": 1}])

    events = producer.ctx.db.get_events(event_type=EventType.FORECAST_V1, source=producer.name, limit=10)
    assert forecast is not None
    assert len(events) == 1
    assert events[0].type == EventType.FORECAST_V1
    assert events[0].payload["forecast_id"] == forecast.forecast_id
    assert events[0].payload["action"] == "long"


def test_source_property_uses_producer_name_and_version() -> None:
    interpreter = NullInterpreter()
    interpreter.producer_name = "demo"
    interpreter.producer_version = "9.9.9"

    assert interpreter.source == "demo@9.9.9"


def test_emit_forecast_wires_producer_name_into_interpreter_source(tmp_path) -> None:
    producer = _TestProducer(_make_ctx(tmp_path))
    producer.interpreter = NullInterpreter()
    producer.interpreter.producer_version = "2.0.0"

    forecast = producer.emit_forecast(asset="SOL", horizon="1h")

    assert forecast is not None
    assert forecast.source == "test-producer@2.0.0"
