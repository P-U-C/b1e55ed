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
from engine.producers.curator import CuratorIntelProducer


class DummyClient:
    def __init__(self, response: httpx.Response | None = None, exc: Exception | None = None):
        self._response = response
        self._exc = exc

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self._exc is not None:
            raise self._exc
        assert self._response is not None
        return self._response


def test_curator_intel_producer_publishes_events_from_url(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("B1E55ED_CURATOR_URL", "https://example.test/curator")

    resp = httpx.Response(
        200,
        json={
            "data": [
                {
                    "symbol": "ETH",
                    "direction": "bearish",
                    "conviction": 0.66,
                    "rationale": "ETF flows fading",
                    "source": "operator",
                }
            ]
        },
        request=httpx.Request("GET", "https://example.test/curator"),
    )

    db = Database(tmp_path / "events.db")
    ctx = ProducerContext(
        config=Config(),
        db=db,
        client=DummyClient(response=resp),
        metrics=MetricsRegistry(),
        logger=logging.getLogger("test"),
    )

    pr = CuratorIntelProducer(ctx).run()
    assert pr.events_published == 1

    events = db.get_events(event_type=EventType.SIGNAL_CURATOR_V1, source="curator-intel", limit=10)
    assert len(events) == 1

    ev = events[0]
    assert ev.payload["symbol"] == "ETH"
    assert ev.payload["direction"] == "bearish"
    assert ev.payload["conviction"] == 0.66
    assert ev.payload["rationale"] == "ETF flows fading"
    assert ev.payload["source"] == "operator"
    assert ev.dedupe_key and "curator-intel" in ev.dedupe_key


def test_curator_intel_producer_handles_401(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("B1E55ED_CURATOR_URL", "https://example.test/curator")

    req = httpx.Request("GET", "https://example.test/curator")
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

    pr = CuratorIntelProducer(ctx).run()
    assert pr.events_published == 0
    assert pr.health == ProducerHealth.DEGRADED
    assert pr.errors and "401" in pr.errors[0]
