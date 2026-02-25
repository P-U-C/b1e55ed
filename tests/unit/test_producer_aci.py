from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest

from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType
from engine.core.metrics import MetricsRegistry
from engine.core.types import ProducerHealth
from engine.producers.aci import ACIProducer, parse_score
from engine.producers.base import ProducerContext


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


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("score: 7", 7),
        ("-3", -3),
        ("final: -11", -10),
        ("final: 42", 10),
        ("no integers here", 0),
        ("first 1 then 2 then 3", 3),
        ("chain: -1 / 0 / +9", 9),
        ("think 9\nanswer -2", -2),
        ('JSON-ish {"score": 4} trailing 6', 6),
        ("0 0 0", 0),
    ],
)
def test_parse_score_extracts_last_int_and_clamps(text: str, expected: int) -> None:
    assert parse_score(text) == expected


def test_parse_score_unwraps_dict() -> None:
    assert parse_score({"score": "blah 1 blah 2"}) == 2
    assert parse_score({"consensus_score": -99}) == -10
    assert parse_score({"text": "7"}) == 7


def test_aci_producer_publishes_events(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("B1E55ED_ACI_URL", "https://example.test/aci")

    resp = httpx.Response(
        200,
        json={
            "data": [
                {
                    "symbol": "BTC",
                    "response": "analysis... score: -12\nfinal: -9",
                    "models_queried": 3,
                    "models_responded": 2,
                    "dispersion": 1.25,
                }
            ]
        },
        request=httpx.Request("POST", "https://example.test/aci"),
    )

    db = Database(tmp_path / "aci.db")
    ctx = ProducerContext(
        config=Config(),
        db=db,
        client=DummyClient(response=resp),
        metrics=MetricsRegistry(),
        logger=logging.getLogger("test"),
    )

    pr = ACIProducer(ctx).run()
    assert pr.events_published == 1

    events = db.get_events(event_type=EventType.SIGNAL_ACI_V1, source="ai-consensus", limit=10)
    assert len(events) == 1
    assert events[0].payload["symbol"] == "BTC"
    assert events[0].payload["consensus_score"] == -9.0
    assert events[0].payload["models_queried"] == 3
    assert events[0].payload["models_responded"] == 2
    assert events[0].dedupe_key and "ai-consensus" in events[0].dedupe_key


def test_aci_producer_handles_401(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("B1E55ED_ACI_URL", "https://example.test/aci")

    req = httpx.Request("POST", "https://example.test/aci")
    resp = httpx.Response(401, json={"error": "unauthorized"}, request=req)
    exc = httpx.HTTPStatusError("unauthorized", request=req, response=resp)

    db = Database(tmp_path / "aci.db")
    ctx = ProducerContext(
        config=Config(),
        db=db,
        client=DummyClient(exc=exc),
        metrics=MetricsRegistry(),
        logger=logging.getLogger("test"),
    )

    pr = ACIProducer(ctx).run()
    assert pr.events_published == 0
    assert pr.health == ProducerHealth.DEGRADED
    assert pr.errors and "401" in pr.errors[0]
