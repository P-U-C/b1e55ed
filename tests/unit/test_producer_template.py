from __future__ import annotations

import logging

from engine.core.client import DataClient
from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType
from engine.core.metrics import MetricsRegistry
from engine.producers.base import ProducerContext
from engine.producers.template import TemplateProducer


def test_template_producer_runs_end_to_end(tmp_path) -> None:
    db = Database(tmp_path / "events.db")
    ctx = ProducerContext(
        config=Config(),
        db=db,
        client=DataClient(),
        metrics=MetricsRegistry(),
        logger=logging.getLogger("test"),
    )

    pr = TemplateProducer(ctx).run()
    assert pr.events_published == 1
    assert pr.errors == []

    events = db.get_events(event_type=EventType.SIGNAL_EVENTS_V1, source="template", limit=10)
    assert len(events) == 1
    assert events[0].payload["catalysts"] == ["template"]
    assert db.verify_hash_chain(fast=False)
