from __future__ import annotations

import logging
from typing import Any

import httpx

from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType
from engine.core.metrics import MetricsRegistry
from engine.core.types import ProducerResult
from engine.producers.base import ProducerContext
from engine.producers.registry import get_producer, list_producers


class DummyClient:
    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        # Default "safe" response shape for producers that expect a list.
        return httpx.Response(
            200,
            json={"data": []},
            request=httpx.Request(method, url),
        )


def test_all_registered_producers_follow_contract(monkeypatch, tmp_path) -> None:
    # Keep the contract test hermetic: no accidental network calls.
    # If a producer endpoint env var is set in the environment, it will still
    # hit DummyClient and get a benign empty payload.

    producer_names = list_producers()
    assert producer_names, "expected at least one registered producer"

    known_event_types = set(EventType)

    for name in producer_names:
        cls = get_producer(name)

        db = Database(tmp_path / f"{name}.db")
        ctx = ProducerContext(
            config=Config(),
            db=db,
            client=DummyClient(),
            metrics=MetricsRegistry(),
            logger=logging.getLogger("test"),
        )

        producer = cls(ctx)  # type: ignore[call-arg]

        # Contract: run() never raises.
        result = producer.run()
        assert isinstance(result, ProducerResult)

        events = db.get_events(limit=500)
        assert all(ev.type in known_event_types for ev in events)
