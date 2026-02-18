from __future__ import annotations

import dataclasses
import logging
from datetime import UTC, datetime

from engine.core.client import DataClient
from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType
from engine.core.metrics import MetricsRegistry
from engine.producers.base import (
    BaseProducer,
    Producer,
    ProducerContext,
    ProducerHealth,
    ProducerResult,
)


class _GoodProducer:
    name = "good"
    domain = "events"
    schedule = "continuous"

    def collect(self) -> list[dict]:
        return []

    def normalize(self, raw: list[dict]):  # type: ignore[no-untyped-def]
        return []

    def publish(self, events):  # type: ignore[no-untyped-def]
        return 0

    def run(self) -> ProducerResult:
        return ProducerResult(
            events_published=0,
            errors=[],
            duration_ms=0,
            timestamp=datetime.now(tz=UTC),
        )


class _BadProducer:
    name = "bad"
    domain = "events"
    schedule = "continuous"

    def collect(self) -> list[dict]:
        return []


def test_protocol_runtime_checkable() -> None:
    assert isinstance(_GoodProducer(), Producer)
    assert not isinstance(_BadProducer(), Producer)


def test_producer_result_is_dataclass_and_serializable() -> None:
    pr = ProducerResult(
        events_published=3,
        errors=["x"],
        duration_ms=12,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        staleness_ms=500,
        health=ProducerHealth.DEGRADED,
    )
    assert dataclasses.is_dataclass(pr)
    d = dataclasses.asdict(pr)
    assert d["events_published"] == 3
    assert d["health"] == ProducerHealth.DEGRADED


def test_producer_health_enum_values() -> None:
    assert ProducerHealth.OK.value == "ok"
    assert ProducerHealth.ERROR.value == "error"


def test_base_producer_run_template_method_publishes(tmp_path) -> None:
    db = Database(tmp_path / "events.db")
    ctx = ProducerContext(
        config=Config(),
        db=db,
        client=DataClient(),
        metrics=MetricsRegistry(),
        logger=logging.getLogger("test"),
    )

    class P(BaseProducer):
        name = "p"
        domain = "events"
        schedule = "continuous"

        def collect(self) -> list[dict]:
            return [{"x": 1}]

        def normalize(self, raw: list[dict]):
            assert raw == [{"x": 1}]
            return [
                self.draft_event(
                    event_type=EventType.SIGNAL_EVENTS_V1,
                    payload={
                        "symbol": "BTC",
                        "headline_sentiment": None,
                        "impact_score": None,
                        "event_count": 0,
                        "catalysts": ["unit"],
                    },
                )
            ]

    pr = P(ctx).run()
    assert pr.events_published == 1
    assert pr.errors == []

    events = db.get_events(event_type=EventType.SIGNAL_EVENTS_V1, source="p", limit=10)
    assert len(events) == 1
    assert db.verify_hash_chain(fast=False)


def test_base_producer_run_handles_exceptions(tmp_path) -> None:
    db = Database(tmp_path / "events.db")
    ctx = ProducerContext(
        config=Config(),
        db=db,
        client=DataClient(),
        metrics=MetricsRegistry(),
        logger=logging.getLogger("test"),
    )

    class P(BaseProducer):
        name = "broken"
        domain = "events"
        schedule = "continuous"

        def collect(self) -> list[dict]:
            raise RuntimeError("boom")

        def normalize(self, raw: list[dict]):  # pragma: no cover
            return []

    pr = P(ctx).run()
    assert pr.events_published == 0
    assert pr.health == ProducerHealth.ERROR
    assert pr.errors and "RuntimeError" in pr.errors[0]
