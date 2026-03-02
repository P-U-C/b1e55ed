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
from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    UTC = UTC  # noqa: N806

from typing import Any, Protocol, runtime_checkable

from engine.core.client import DataClient
from engine.core.config import Config
from engine.core.database import Database
from engine.core.metrics import MetricsRegistry
from engine.core.models import Event, compute_event_hash
from engine.core.types import CANONICAL_DOMAINS, ProducerHealth, ProducerResult


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

    # Class variable — override in subclasses that have an MCP source.
    mcp_source_url: str | None = None

    # Injected by registry after construction (set in S2).
    _mcp_client: Any | None = None

    # Bertrand Meyer's precondition: enforce contracts at the boundary, not downstream.
    # A producer with an invalid domain fails at construction. Wrong names cost nothing to reject early.
    def __init__(self, ctx: ProducerContext) -> None:
        self.ctx = ctx
        if self.domain not in CANONICAL_DOMAINS:
            raise ValueError(f"Producer '{self.name}' has invalid domain '{self.domain}'. Must be one of: {sorted(CANONICAL_DOMAINS)}")
        self._register_with_mcp()

    def _register_with_mcp(self) -> None:
        """Register this producer with the MCP registry. Never raises."""

        try:
            from datetime import UTC

            from engine.mcp.registry import get_registry
            from engine.mcp.types import MCPProducerManifest

            manifest = MCPProducerManifest(
                name=self.name,
                domain=self.domain,
                mcp_source_url=getattr(self, "mcp_source_url", None),
                description=getattr(self, "__doc__", "") or "",
                assets=getattr(self, "assets", []),
                schedule=self.schedule,
                registered_at=datetime.now(tz=UTC).isoformat(),
            )
            get_registry().register(manifest)
        except Exception:  # noqa: BLE001
            pass

    def _collect_via_mcp(self) -> list[dict]:
        """Fetch raw data via MCP client. Returns [] on any failure."""

        if self._mcp_client is None:
            return []

        try:
            result = self._mcp_client.call_tool("get_signals", {"producer": self.name})
            return result.data
        except Exception:  # noqa: BLE001
            self.ctx.logger.warning("mcp_collect_failed", extra={"producer": self.name})
            return []

    def _publish_to_mcp(self, events: list[Event]) -> None:
        """Push events to MCP registry. Fire-and-forget — never raises."""

        try:
            from engine.mcp.registry import get_registry
            from engine.mcp.types import MCPSignalPayload

            registry = get_registry()
            for ev in events:
                payload = ev.payload if hasattr(ev, "payload") else {}
                signal = MCPSignalPayload(
                    producer=self.name,
                    domain=self.domain,
                    asset=payload.get("asset") or payload.get("symbol") or payload.get("ticker"),
                    direction=payload.get("direction") or payload.get("signal"),
                    confidence=payload.get("confidence") or payload.get("score"),
                    horizon=payload.get("horizon"),
                    reason=payload.get("reason") or payload.get("rationale") or ev.type,
                    timestamp=ev.ts.isoformat() if hasattr(ev.ts, "isoformat") else str(ev.ts),
                    raw_score=payload.get("raw_score") or payload.get("score"),
                    metadata={"event_type": ev.type, "source": ev.source},
                )
                registry.push_signal(signal)
        except Exception:  # noqa: BLE001
            pass

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

        try:
            self._publish_to_mcp(events)
        except Exception:  # noqa: BLE001
            self.ctx.logger.warning("mcp_publish_failed", extra={"producer": self.name})

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
