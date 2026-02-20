from __future__ import annotations

import logging
from typing import Any

import httpx

from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType
from engine.core.metrics import MetricsRegistry
from engine.core.types import ProducerHealth
from engine.producers.base import ProducerContext
from engine.producers.price_ws import PriceAlertsProducer


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


def test_price_ws_producer_publishes_events(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("B1E55ED_PRICE_WS_URL", "https://example.test/prices")

    resp = httpx.Response(
        200,
        json={
            "data": [
                {
                    "symbol": "BTC",
                    "price": 42000.0,
                    "bid": 41999.5,
                    "ask": 42000.5,
                    "venue": "paper",
                }
            ]
        },
        request=httpx.Request("POST", "https://example.test/prices"),
    )

    db = Database(tmp_path / "events.db")
    ctx = ProducerContext(
        config=Config(),
        db=db,
        client=DummyClient(response=resp),
        metrics=MetricsRegistry(),
        logger=logging.getLogger("test"),
    )

    pr = PriceAlertsProducer(ctx).run()
    assert pr.events_published == 1
    assert pr.health == ProducerHealth.OK

    events = db.get_events(event_type=EventType.SIGNAL_PRICE_WS_V1, source="price-alerts", limit=10)
    assert len(events) == 1
    assert events[0].type == EventType.SIGNAL_PRICE_WS_V1
    assert events[0].payload["symbol"] == "BTC"
    assert events[0].payload["price"] == 42000.0
    assert events[0].dedupe_key and "price-alerts" in events[0].dedupe_key


def test_price_ws_producer_handles_401(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("B1E55ED_PRICE_WS_URL", "https://example.test/prices")

    req = httpx.Request("POST", "https://example.test/prices")
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

    pr = PriceAlertsProducer(ctx).run()
    assert pr.events_published == 0
    assert pr.health == ProducerHealth.DEGRADED
    assert pr.errors and "401" in pr.errors[0]
