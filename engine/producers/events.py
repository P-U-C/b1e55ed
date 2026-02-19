"""engine.producers.events

Market Events Producer.

Treats the configured endpoint as a simple HTTP poller that returns a list of
"events" / catalysts per symbol, then emits
:class:`~engine.core.events.EventType.SIGNAL_EVENTS_V1`.

The endpoint is configured via env and unit tests mock the injected
``context.client``.

Easter egg:
- News is noise; catalysts are structure.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from engine.core.events import EventsSignalPayload, EventType, payload_hash
from engine.core.models import Event
from engine.core.types import ProducerHealth, ProducerResult
from engine.producers.base import BaseProducer
from engine.producers.registry import register


def _dedupe_key(*, producer: str, payload: dict[str, Any]) -> str:
    """Deterministic dedupe key based on canonicalized payload."""

    return f"{EventType.SIGNAL_EVENTS_V1}:{producer}:{payload_hash(payload)}"


@register("market-events", domain="events")
class MarketEventsProducer(BaseProducer):
    schedule = "*/30 * * * *"

    def _endpoint(self) -> str | None:
        return os.getenv("B1E55ED_EVENTS_URL") or os.getenv("EVENTS_URL")

    def collect(self) -> list[dict[str, Any]]:
        url = self._endpoint()
        if not url:
            self.ctx.logger.warning("events_endpoint_missing")
            return []

        symbols = [s.upper().strip() for s in self.ctx.config.universe.symbols]
        resp = asyncio.run(self.ctx.client.request("POST", url, json={"symbols": symbols}))

        data: Any = resp.json()
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        if not isinstance(data, list):
            return []
        return [row for row in data if isinstance(row, dict)]

    def normalize(self, raw: list[dict[str, Any]]) -> list[Event]:
        ts = datetime.now(tz=UTC)
        out: list[Event] = []

        for row in raw:
            sym = str(row.get("symbol") or row.get("asset") or "").upper().strip()
            if not sym:
                continue

            catalysts_raw = row.get("catalysts") or row.get("events") or []
            catalysts: list[str] = []
            if isinstance(catalysts_raw, list):
                catalysts = [str(x) for x in catalysts_raw if x is not None and str(x).strip()]
            elif isinstance(catalysts_raw, str) and catalysts_raw.strip():
                catalysts = [catalysts_raw.strip()]

            event_count = row.get("event_count")
            if not isinstance(event_count, int):
                event_count = len(catalysts)

            payload_obj = EventsSignalPayload(
                symbol=sym,
                headline_sentiment=row.get("headline_sentiment"),
                impact_score=row.get("impact_score"),
                event_count=event_count,
                catalysts=catalysts,
            )
            payload = payload_obj.model_dump(mode="json")

            out.append(
                self.draft_event(
                    event_type=EventType.SIGNAL_EVENTS_V1,
                    payload=payload,
                    ts=ts,
                    observed_at=ts,
                    source=self.name,
                    dedupe_key=_dedupe_key(producer=self.name, payload=payload),
                )
            )

        return out

    def run(self) -> ProducerResult:
        """Run with producer isolation: never raise."""

        start = time.perf_counter()
        errors: list[str] = []
        published = 0
        health: ProducerHealth = ProducerHealth.OK

        try:
            raw = self.collect()
            if not raw:
                health = ProducerHealth.DEGRADED
            events = self.normalize(raw)
            published = self.publish(events)
        except httpx.HTTPStatusError as e:
            code = getattr(e.response, "status_code", None)
            health = ProducerHealth.DEGRADED if code in (401, 403) else ProducerHealth.ERROR
            errors.append(f"HTTPStatusError: {code}")
        except Exception as e:  # noqa: BLE001
            health = ProducerHealth.ERROR
            errors.append(f"{type(e).__name__}: {e}")
            self.ctx.logger.exception("events_run_failed")

        duration_ms = int((time.perf_counter() - start) * 1000)
        return ProducerResult(
            events_published=published,
            errors=errors,
            duration_ms=duration_ms,
            timestamp=datetime.now(tz=UTC),
            staleness_ms=None,
            health=health,
        )
