"""engine.producers.base

Producers are the sensory organs of the system.

They observe the world, distill observations into events, and hand those events to the
rest of the pipeline. The brain cannot reason about what the producers cannot see.

Observation protocol:
- collect raw facts
- normalize into the event contract
- publish into the hash-chained journal
"""

from __future__ import annotations

import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from engine.core.client import DataClient
from engine.core.config import Config
from engine.core.database import Database
from engine.core.metrics import MetricsRegistry
from engine.core.models import Event, compute_event_hash
from engine.core.types import ProducerHealth, ProducerResult


@dataclass(frozen=True, slots=True)
class ProducerContext:
    """Shared context injected into every producer."""

    config: Config
    db: Database
    client: DataClient
    metrics: MetricsRegistry
    logger: logging.Logger


@runtime_checkable
class Producer(Protocol):
    name: str
    domain: str  # "technical" | "onchain" | "tradfi" | "social" | "events" | "curator"
    schedule: str  # Cron expression or "continuous"

    def collect(self) -> list[dict]: ...

    def normalize(self, raw: list[dict]) -> list[Event]: ...

    def publish(self, events: list[Event]) -> int: ...

    def run(self) -> ProducerResult: ...


class BaseProducer(ABC):
    """Template-method base class.

    Subclasses typically implement:
    - collect()
    - normalize()

    and inherit:
    - publish() (default: append to the event store)
    - run() (collect → normalize → publish)
    """

    name: str
    domain: str
    schedule: str

    def __init__(self, ctx: ProducerContext) -> None:
        self.ctx = ctx

    @abstractmethod
    def collect(self) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def normalize(self, raw: list[dict]) -> list[Event]:
        raise NotImplementedError

    def publish(self, events: list[Event]) -> int:
        """Default publisher: append events to the database.

        Producers may return "draft" Event objects (placeholder id/hash). The database
        remains the source of truth for ids + the hash chain.
        """

        published = 0
        for ev in events:
            self.ctx.db.append_event(
                event_type=ev.type,
                payload=ev.payload,
                ts=ev.ts,
                observed_at=ev.observed_at,
                source=ev.source or self.name,
                trace_id=ev.trace_id,
                schema_version=ev.schema_version,
                dedupe_key=ev.dedupe_key,
            )
            published += 1
        return published

    def run(self) -> ProducerResult:
        start = time.perf_counter()
        errors: list[str] = []
        published = 0
        health: ProducerHealth = ProducerHealth.OK
        staleness_ms: int | None = None

        try:
            raw = self.collect()
            events = self.normalize(raw)
            published = self.publish(events)
        except Exception as e:  # noqa: BLE001 - producer isolation boundary
            health = ProducerHealth.ERROR
            errors.append(f"{type(e).__name__}: {e}")
            self.ctx.logger.exception("producer_run_failed", extra={"producer": self.name})

        duration_ms = int((time.perf_counter() - start) * 1000)
        return ProducerResult(
            events_published=published,
            errors=errors,
            duration_ms=duration_ms,
            timestamp=datetime.now(tz=UTC),
            staleness_ms=staleness_ms,
            health=health,
        )

    def draft_event(
        self,
        *,
        event_type,
        payload: dict,
        ts: datetime | None = None,
        observed_at: datetime | None = None,
        source: str | None = None,
        trace_id: str | None = None,
        dedupe_key: str | None = None,
    ) -> Event:
        """Create a minimal Event suitable for passing to publish()."""

        ts_ = ts or datetime.now(tz=UTC)
        if ts_.tzinfo is None:
            ts_ = ts_.replace(tzinfo=UTC)

        eid = str(uuid.uuid4())
        src = source or self.name
        h = compute_event_hash(
            prev_hash=None,
            event_type=event_type,
            payload=payload,
            ts=ts_,
            source=src,
            trace_id=trace_id,
            schema_version="v1",
            dedupe_key=dedupe_key,
            event_id=eid,
        )
        return Event(
            id=eid,
            type=event_type,
            ts=ts_,
            observed_at=observed_at,
            source=src,
            trace_id=trace_id,
            schema_version="v1",
            dedupe_key=dedupe_key,
            payload=payload,
            prev_hash=None,
            hash=h,
        )
