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
from engine.producers.orderbook import OrderbookDepthProducer


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


def test_orderbook_producer_publishes_events(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("B1E55ED_ORDERBOOK_URL", "https://example.test/orderbook")

    resp = httpx.Response(
        200,
        json={
            "data": [
                {
                    "symbol": "ETH",
                    "bid_depth_usd": 1_000_000.0,
                    "ask_depth_usd": 900_000.0,
                    "imbalance": 0.0526,
                    "lod_score": 0.7,
                }
            ]
        },
        request=httpx.Request("POST", "https://example.test/orderbook"),
    )

    db = Database(tmp_path / "events.db")
    ctx = ProducerContext(
        config=Config(),
        db=db,
        client=DummyClient(response=resp),
        metrics=MetricsRegistry(),
        logger=logging.getLogger("test"),
    )

    pr = OrderbookDepthProducer(ctx).run()
    assert pr.events_published == 1

    events = db.get_events(
        event_type=EventType.SIGNAL_ORDERBOOK_V1,
        source="orderbook-depth",
        limit=10,
    )
    assert len(events) == 1
    assert events[0].payload["symbol"] == "ETH"
    assert events[0].dedupe_key and "orderbook-depth" in events[0].dedupe_key


def test_orderbook_producer_handles_401(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("B1E55ED_ORDERBOOK_URL", "https://example.test/orderbook")

    req = httpx.Request("POST", "https://example.test/orderbook")
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

    pr = OrderbookDepthProducer(ctx).run()
    assert pr.events_published == 0
    assert pr.health == ProducerHealth.DEGRADED
    assert pr.errors and "401" in pr.errors[0]
