from __future__ import annotations

from datetime import UTC, datetime

import pytest

from engine.core.database import Database
from engine.core.events import EventType
from engine.core.ingestion import AggregationBus, EventPublisher


def test_bus_routes_events_to_handlers_and_dedupes(tmp_path) -> None:
    db = Database(tmp_path / "db.sqlite")
    bus = AggregationBus()
    pub = EventPublisher(db=db, bus=bus, default_source="test")

    seen: list[str] = []

    def handler(ev):
        seen.append(ev.id)

    bus.register_handler(EventType.SIGNAL_TA_V1, handler)

    payload = {"symbol": "BTC", "rsi_14": 55.0}
    ev = pub.publish(EventType.SIGNAL_TA_V1, payload, trace_id="t1", ts=datetime(2026, 1, 1, tzinfo=UTC))
    assert seen == [ev.id]

    with pytest.raises(ValueError):
        pub.publish(
            EventType.SIGNAL_TA_V1,
            payload,
            trace_id="t1",
            dedupe_key=ev.dedupe_key,
            ts=datetime(2026, 1, 1, tzinfo=UTC),
        )

    db.close()
