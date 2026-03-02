from __future__ import annotations

import logging
from typing import Any

import httpx

from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import AbstentionReason, EventType, ForecastPayload
from engine.core.metrics import MetricsRegistry
from engine.core.types import ProducerHealth
from engine.producers.base import ProducerContext
from engine.producers.tradfi import TradFiBasisInterpreter, TradFiBasisProducer


class DummyClient:
    def __init__(self, response: httpx.Response | None = None, exc: Exception | None = None):
        self._response = response
        self._exc = exc

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self._exc is not None:
            raise self._exc
        assert self._response is not None
        return self._response

    async def request_json(self, method: str, url: str, **kwargs: Any) -> Any:
        resp = await self.request(method, url, **kwargs)
        return resp.json()


def _signal(*, symbol: str, direction: str, confidence: float, reason: str = "signal") -> dict[str, Any]:
    return {
        "symbol": symbol,
        "basis_annualized": 4.0,
        "funding_annualized": 10.0,
        "meltup_score": 2,
        "direction": direction,
        "confidence": confidence,
        "signal_reason": reason,
    }


def test_tradfi_interpreter_long_signal() -> None:
    interpreter = TradFiBasisInterpreter()

    payload = interpreter.interpret(asset="BTC", horizon="4h", signals=[_signal(symbol="BTC", direction="long", confidence=0.7)])

    assert isinstance(payload, ForecastPayload)
    assert payload.action == "long"
    assert payload.confidence == 0.7


def test_tradfi_interpreter_short_signal() -> None:
    interpreter = TradFiBasisInterpreter()

    payload = interpreter.interpret(asset="BTC", horizon="4h", signals=[_signal(symbol="BTC", direction="short", confidence=0.8)])

    assert payload.action == "short"
    assert payload.confidence == 0.8


def test_tradfi_interpreter_low_confidence_abstains() -> None:
    interpreter = TradFiBasisInterpreter()

    payload = interpreter.interpret(asset="BTC", horizon="4h", signals=[_signal(symbol="BTC", direction="long", confidence=0.2)])

    assert payload.action == "no_forecast"
    assert payload.abstention_reason == AbstentionReason.INSUFFICIENT_DATA


def test_tradfi_interpreter_missing_asset_abstains() -> None:
    interpreter = TradFiBasisInterpreter()

    payload = interpreter.interpret(asset="ETH", horizon="4h", signals=[_signal(symbol="BTC", direction="long", confidence=0.7)])

    assert payload.action == "no_forecast"
    assert payload.abstention_reason == AbstentionReason.INSUFFICIENT_DATA


def test_tradfi_basis_producer_publishes_events(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("B1E55ED_TRADFI_BASIS_URL", "https://example.test/basis")

    resp = httpx.Response(
        200,
        json={
            "data": [
                {
                    "symbol": "BTC",
                    "basis_annualized": 0.06,
                    "funding_annualized": 0.02,
                    "oi_change_pct": 1.5,
                    "meltup_score": 0.1,
                }
            ]
        },
        request=httpx.Request("POST", "https://example.test/basis"),
    )

    db = Database(tmp_path / "events.db")
    ctx = ProducerContext(
        config=Config(),
        db=db,
        client=DummyClient(response=resp),
        metrics=MetricsRegistry(),
        logger=logging.getLogger("test"),
    )

    pr = TradFiBasisProducer(ctx).run()
    assert pr.events_published == 1

    events = db.get_events(event_type=EventType.SIGNAL_TRADFI_V1, source="tradfi-basis", limit=10)
    assert len(events) == 1

    ev = events[0]
    assert ev.payload["symbol"] == "BTC"
    assert ev.payload["basis_annualized"] == 0.06
    assert ev.dedupe_key and "tradfi-basis" in ev.dedupe_key


def test_tradfi_dual_write_emits_both_events(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("B1E55ED_TRADFI_BASIS_URL", "https://example.test/basis")

    resp = httpx.Response(
        200,
        json={
            "data": [
                {
                    "symbol": "BTC",
                    "basis_annualized": 4.0,
                    "funding_annualized": 10.0,
                    "oi_change_pct": 1.5,
                    "meltup_score": 2.0,
                }
            ]
        },
        request=httpx.Request("POST", "https://example.test/basis"),
    )

    db = Database(tmp_path / "events.db")
    cfg = Config(universe={"symbols": ["BTC", "ETH"]})
    ctx = ProducerContext(
        config=cfg,
        db=db,
        client=DummyClient(response=resp),
        metrics=MetricsRegistry(),
        logger=logging.getLogger("test"),
    )

    pr = TradFiBasisProducer(ctx).run()

    signal_events = db.get_events(event_type=EventType.SIGNAL_TRADFI_V1, source="tradfi-basis", limit=10)
    forecast_events = db.get_events(event_type=EventType.FORECAST_V1, source="tradfi-basis", limit=10)

    assert pr.events_published == 1
    assert len(signal_events) == 1
    assert len(forecast_events) == 2
    assert {event.payload["asset"] for event in forecast_events} == {"BTC", "ETH"}
    assert any(event.payload["action"] == "long" for event in forecast_events)
    assert any(event.payload["action"] == "no_forecast" for event in forecast_events)


def test_tradfi_basis_producer_handles_401(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("B1E55ED_TRADFI_BASIS_URL", "https://example.test/basis")

    req = httpx.Request("POST", "https://example.test/basis")
    resp = httpx.Response(401, json={"error": "unauthorized"}, request=req)
    exc = httpx.HTTPStatusError("unauthorized", request=req, response=resp)

    db = Database(tmp_path / "events.db")
    ctx = ProducerContext(
        config=Config(),
        db=db,
        client=DummyClient(exc=exc),
        metrics=MetricsRegistry(),
        logger=logging.getLogger("test"),
    )

    pr = TradFiBasisProducer(ctx).run()
    assert pr.events_published == 0
    assert pr.health == ProducerHealth.DEGRADED
    assert pr.errors and "401" in pr.errors[0]
