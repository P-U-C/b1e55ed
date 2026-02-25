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
from engine.producers.events import MarketEventsProducer


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


def test_events_producer_publishes_events(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("B1E55ED_EVENTS_URL", "https://example.test/events")

    resp = httpx.Response(
        200,
        json={
            "data": [
                {
                    "symbol": "BTC",
                    "headline_sentiment": 0.25,
                    "impact_score": 0.9,
                    "event_count": 2,
                    "catalysts": ["ETF flow", "FOMC"],
                }
            ]
        },
        request=httpx.Request("POST", "https://example.test/events"),
    )

    db = Database(tmp_path / "events.db")
    ctx = ProducerContext(
        config=Config(),
        db=db,
        client=DummyClient(response=resp),
        metrics=MetricsRegistry(),
        logger=logging.getLogger("test"),
    )

    pr = MarketEventsProducer(ctx).run()
    assert pr.events_published == 1

    events = db.get_events(event_type=EventType.SIGNAL_EVENTS_V1, source="market-events", limit=10)
    assert len(events) == 1
    assert events[0].payload["symbol"] == "BTC"
    assert events[0].payload["event_count"] == 2
    assert events[0].payload["catalysts"] == ["ETF flow", "FOMC"]
    assert events[0].dedupe_key and "market-events" in events[0].dedupe_key


def test_events_producer_handles_403(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("B1E55ED_EVENTS_URL", "https://example.test/events")

    req = httpx.Request("POST", "https://example.test/events")
    resp = httpx.Response(403, json={"error": "forbidden"}, request=req)
    exc = httpx.HTTPStatusError("forbidden", request=req, response=resp)

    db = Database(tmp_path / "events.db")
    ctx = ProducerContext(
        config=Config(),
        db=db,
        client=DummyClient(exc=exc),
        metrics=MetricsRegistry(),
        logger=logging.getLogger("test"),
    )

    pr = MarketEventsProducer(ctx).run()
    assert pr.events_published == 0
    assert pr.health == ProducerHealth.DEGRADED
    assert pr.errors and "403" in pr.errors[0]
