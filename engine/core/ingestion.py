"""engine.core.ingestion

Aggregation bus + event publisher.

All signals eventually reach the brain.

The bus is intentionally small:
- compute dedupe keys (optional)
- append to the event store
- fan out to in-process handlers (e.g. projections)

The event store remains the source of truth for dedupe across restarts.
The bus adds an in-memory fast path to prevent hot-loop duplicates.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from engine.core.database import Database
from engine.core.events import EventType, compute_dedupe_key
from engine.core.models import Event

EventHandler = Callable[[Event], None]


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass
class AggregationBus:
    """Routes events to registered handlers by type and deduplicates by dedupe_key."""

    _handlers: dict[str, list[EventHandler]] = field(default_factory=dict)
    _seen_dedupe: set[str] = field(default_factory=set)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def register_handler(self, event_type: EventType | str, handler: EventHandler) -> None:
        et = str(event_type)
        with self._lock:
            self._handlers.setdefault(et, []).append(handler)

    def route(self, event: Event) -> None:
        with self._lock:
            handlers = list(self._handlers.get(str(event.type), []))
        for h in handlers:
            h(event)

    def append_and_route(
        self,
        db: Database,
        *,
        event_type: EventType,
        payload: dict[str, Any],
        trace_id: str | None = None,
        source: str | None = None,
        observed_at: datetime | None = None,
        dedupe_key: str | None = None,
        ts: datetime | None = None,
    ) -> Event:
        dkey = dedupe_key or compute_dedupe_key(event_type, payload)

        with self._lock:
            if dkey in self._seen_dedupe:
                raise ValueError(f"duplicate dedupe_key rejected by bus: {dkey}")
            self._seen_dedupe.add(dkey)

        ev = db.append_event(
            event_type=event_type,
            payload=payload,
            trace_id=trace_id,
            source=source,
            observed_at=observed_at,
            dedupe_key=dkey,
            ts=ts or _utc_now(),
        )

        self.route(ev)
        return ev


@dataclass
class EventPublisher:
    """Publishes events to the store through the bus."""

    db: Database
    bus: AggregationBus
    default_source: str | None = None

    def publish(
        self,
        event_type: EventType,
        payload: BaseModel | dict[str, Any],
        *,
        trace_id: str | None = None,
        dedupe_key: str | None = None,
        source: str | None = None,
        observed_at: datetime | None = None,
        ts: datetime | None = None,
    ) -> Event:
        obj = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else dict(payload)
        return self.bus.append_and_route(
            self.db,
            event_type=event_type,
            payload=obj,
            trace_id=trace_id,
            source=source or self.default_source,
            observed_at=observed_at,
            dedupe_key=dedupe_key,
            ts=ts,
        )
