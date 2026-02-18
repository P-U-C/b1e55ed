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
from engine.producers.ta import TechnicalAnalysisProducer


class DummyClient:
    def __init__(self, response: httpx.Response | None = None, exc: Exception | None = None):
        self._response = response
        self._exc = exc

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self._exc is not None:
            raise self._exc
        assert self._response is not None
        return self._response


def test_ta_producer_publishes_events(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("B1E55ED_TA_URL", "https://example.test/ta")

    resp = httpx.Response(
        200,
        json={
            "data": [
                {
                    "symbol": "BTC",
                    "rsi_14": 52.1,
                    "ema_20": 100.0,
                    "ema_50": 99.0,
                    "ema_200": 80.0,
                    "bb_position": 0.4,
                    "volume_ratio": 1.1,
                    "trend": "neutral",
                    "trend_strength": 0.2,
                    "support_distance": 0.03,
                    "resistance_distance": 0.05,
                }
            ]
        },
        request=httpx.Request("POST", "https://example.test/ta"),
    )

    db = Database(tmp_path / "events.db")
    ctx = ProducerContext(
        config=Config(),
        db=db,
        client=DummyClient(response=resp),
        metrics=MetricsRegistry(),
        logger=logging.getLogger("test"),
    )

    pr = TechnicalAnalysisProducer(ctx).run()
    assert pr.events_published == 1

    events = db.get_events(event_type=EventType.SIGNAL_TA_V1, source="technical-analysis", limit=10)
    assert len(events) == 1
    assert events[0].payload["symbol"] == "BTC"
    assert events[0].dedupe_key and "technical-analysis" in events[0].dedupe_key


def test_ta_producer_handles_401(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("B1E55ED_TA_URL", "https://example.test/ta")

    req = httpx.Request("POST", "https://example.test/ta")
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

    pr = TechnicalAnalysisProducer(ctx).run()
    assert pr.events_published == 0
    assert pr.health == ProducerHealth.DEGRADED
    assert pr.errors and "401" in pr.errors[0]
