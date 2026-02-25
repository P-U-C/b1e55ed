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
from engine.producers.etf import ETFFlowsProducer


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


def test_etf_flows_producer_publishes_events(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("B1E55ED_ETF_FLOWS_URL", "https://example.test/etf")

    resp = httpx.Response(
        200,
        json={
            "data": [
                {
                    "symbol": "BTC",
                    "daily_flow_usd": 123_000_000.0,
                    "streak_days": 3,
                    "cumulative_7d": 250_000_000.0,
                }
            ]
        },
        request=httpx.Request("POST", "https://example.test/etf"),
    )

    db = Database(tmp_path / "events.db")
    ctx = ProducerContext(
        config=Config(),
        db=db,
        client=DummyClient(response=resp),
        metrics=MetricsRegistry(),
        logger=logging.getLogger("test"),
    )

    pr = ETFFlowsProducer(ctx).run()
    assert pr.events_published == 1

    events = db.get_events(event_type=EventType.SIGNAL_ETF_V1, source="etf-flows", limit=10)
    assert len(events) == 1

    ev = events[0]
    assert ev.payload["symbol"] == "BTC"
    assert ev.payload["daily_flow_usd"] == 123_000_000.0
    assert ev.payload["streak_days"] == 3
    assert ev.dedupe_key and "etf-flows" in ev.dedupe_key


def test_etf_flows_producer_handles_401(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("B1E55ED_ETF_FLOWS_URL", "https://example.test/etf")

    req = httpx.Request("POST", "https://example.test/etf")
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

    pr = ETFFlowsProducer(ctx).run()
    assert pr.events_published == 0
    assert pr.health == ProducerHealth.DEGRADED
    assert pr.errors and "401" in pr.errors[0]
