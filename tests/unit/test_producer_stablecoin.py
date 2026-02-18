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
from engine.producers.stablecoin import StablecoinSupplyProducer


class DummyClient:
    def __init__(self, response: httpx.Response | None = None, exc: Exception | None = None):
        self._response = response
        self._exc = exc

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self._exc is not None:
            raise self._exc
        assert self._response is not None
        return self._response


def test_stablecoin_producer_publishes_events(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("B1E55ED_STABLECOIN_SUPPLY_URL", "https://example.test/stablecoin/supply")

    resp = httpx.Response(
        200,
        json={
            "data": [
                {
                    "stablecoin": "USDT",
                    "supply_change_24h": 123.0,
                    "supply_change_7d": 456.0,
                    "mint_burn_events": 7,
                }
            ]
        },
        request=httpx.Request("GET", "https://example.test/stablecoin/supply"),
    )

    db = Database(tmp_path / "events.db")
    ctx = ProducerContext(
        config=Config(),
        db=db,
        client=DummyClient(response=resp),
        metrics=MetricsRegistry(),
        logger=logging.getLogger("test"),
    )

    pr = StablecoinSupplyProducer(ctx).run()
    assert pr.events_published == 1

    events = db.get_events(
        event_type=EventType.SIGNAL_STABLECOIN_V1,
        source="stablecoin-supply",
        limit=10,
    )
    assert len(events) == 1
    assert events[0].payload["stablecoin"] == "USDT"
    assert events[0].dedupe_key and "stablecoin-supply" in events[0].dedupe_key


def test_stablecoin_producer_handles_403(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("B1E55ED_STABLECOIN_SUPPLY_URL", "https://example.test/stablecoin/supply")

    req = httpx.Request("GET", "https://example.test/stablecoin/supply")
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

    pr = StablecoinSupplyProducer(ctx).run()
    assert pr.events_published == 0
    assert pr.health == ProducerHealth.DEGRADED
    assert pr.errors and "403" in pr.errors[0]
