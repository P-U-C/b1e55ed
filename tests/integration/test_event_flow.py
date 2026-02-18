from __future__ import annotations

from datetime import UTC, datetime

from engine.core.database import Database
from engine.core.events import EventType
from engine.core.ingestion import AggregationBus, EventPublisher
from engine.core.projections import ProjectionManager


def test_event_flow_producer_bus_store_projection(tmp_path) -> None:
    db = Database(tmp_path / "db.sqlite")

    pm = ProjectionManager()
    bus = AggregationBus()
    bus.register_handler(EventType.SIGNAL_TA_V1, pm.handle)

    pub = EventPublisher(db=db, bus=bus, default_source="producer.ta")

    pub.publish(
        EventType.SIGNAL_TA_V1,
        {"symbol": "BTC", "rsi_14": 42.0},
        trace_id="trace-1",
        ts=datetime(2026, 1, 1, tzinfo=UTC),
    )

    state = pm.get_state()
    assert state["signals_latest"]["BTC"][str(EventType.SIGNAL_TA_V1)]["payload"]["rsi_14"] == 42.0

    events = db.get_events(event_type=EventType.SIGNAL_TA_V1, limit=10)
    assert len(events) == 1
    assert events[0].payload["rsi_14"] == 42.0

    db.close()
