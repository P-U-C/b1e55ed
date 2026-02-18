from __future__ import annotations

import logging

import httpx

from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType
from engine.core.metrics import MetricsRegistry
from engine.core.types import ProducerHealth
from engine.producers.base import ProducerContext
from engine.producers.social import SocialIntelProducer


class DummyClient:
    async def request(self, method: str, url: str, **kwargs):  # pragma: no cover
        raise AssertionError("social producer should not call ctx.client directly")


def test_social_intel_producer_publishes_events(monkeypatch, tmp_path) -> None:
    def fake_run(*, ctx):
        _ = ctx
        return [
            {
                "symbol": "BTC",
                "score": 0.75,
                "direction": "bullish",
                "source_count": 12,
                "contrarian_flag": False,
                "echo_chamber_flag": True,
            }
        ]

    monkeypatch.setattr("engine.social.pipeline.run", fake_run)

    db = Database(tmp_path / "events.db")
    ctx = ProducerContext(
        config=Config(),
        db=db,
        client=DummyClient(),
        metrics=MetricsRegistry(),
        logger=logging.getLogger("test"),
    )

    pr = SocialIntelProducer(ctx).run()
    assert pr.events_published == 1

    events = db.get_events(event_type=EventType.SIGNAL_SOCIAL_V1, source="social-intel", limit=10)
    assert len(events) == 1

    ev = events[0]
    assert ev.payload["symbol"] == "BTC"
    assert ev.payload["score"] == 0.75
    assert ev.payload["direction"] == "bullish"
    assert ev.payload["source_count"] == 12
    assert ev.payload["echo_chamber_flag"] is True
    assert ev.dedupe_key and "social-intel" in ev.dedupe_key


def test_social_intel_producer_handles_403(monkeypatch, tmp_path) -> None:
    req = httpx.Request("GET", "https://example.test/social")
    resp = httpx.Response(403, json={"error": "forbidden"}, request=req)
    exc = httpx.HTTPStatusError("forbidden", request=req, response=resp)

    def fake_run(*, ctx):
        _ = ctx
        raise exc

    monkeypatch.setattr("engine.social.pipeline.run", fake_run)

    db = Database(tmp_path / "events.db")
    ctx = ProducerContext(
        config=Config(),
        db=db,
        client=DummyClient(),
        metrics=MetricsRegistry(),
        logger=logging.getLogger("test"),
    )

    pr = SocialIntelProducer(ctx).run()
    assert pr.events_published == 0
    assert pr.health == ProducerHealth.DEGRADED
    assert pr.errors and "403" in pr.errors[0]
