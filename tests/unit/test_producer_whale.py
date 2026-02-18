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
from engine.producers.whale import WhaleTrackingProducer


class DummyClient:
    def __init__(self, response: httpx.Response | None = None, exc: Exception | None = None):
        self._response = response
        self._exc = exc

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self._exc is not None:
            raise self._exc
        assert self._response is not None
        return self._response


def test_whale_producer_publishes_events(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("B1E55ED_WHALE_TRACKING_URL", "https://example.test/whale")

    resp = httpx.Response(
        200,
        json={
            "data": [
                {
                    "symbol": "ETH",
                    "smart_money_netflow": 10.0,
                    "top_holders_change": -0.02,
                }
            ]
        },
        request=httpx.Request("POST", "https://example.test/whale"),
    )

    db = Database(tmp_path / "events.db")
    ctx = ProducerContext(
        config=Config(),
        db=db,
        client=DummyClient(response=resp),
        metrics=MetricsRegistry(),
        logger=logging.getLogger("test"),
    )

    pr = WhaleTrackingProducer(ctx).run()
    assert pr.events_published == 1

    events = db.get_events(event_type=EventType.SIGNAL_WHALE_V1, source="whale-tracking", limit=10)
    assert len(events) == 1
    assert events[0].payload["symbol"] == "ETH"
    assert events[0].dedupe_key and "whale-tracking" in events[0].dedupe_key


def test_whale_producer_handles_401(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("B1E55ED_WHALE_TRACKING_URL", "https://example.test/whale")

    req = httpx.Request("POST", "https://example.test/whale")
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

    pr = WhaleTrackingProducer(ctx).run()
    assert pr.events_published == 0
    assert pr.health == ProducerHealth.DEGRADED
    assert pr.errors and "401" in pr.errors[0]
