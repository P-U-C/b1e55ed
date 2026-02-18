"""engine.producers.price_ws

Price Alerts Producer (polling placeholder).

This producer is intentionally implemented as a polling loop (HTTP request) even
though the intended long-term interface is a websocket price stream.

It emits :class:`~engine.core.events.EventType.SIGNAL_PRICE_WS_V1` events.

Easter egg:
- There is no "real-time"—only smaller intervals.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from engine.core.events import EventType, PriceWSSignalPayload
from engine.core.models import Event
from engine.core.types import ProducerHealth, ProducerResult
from engine.producers.base import BaseProducer
from engine.producers.registry import register


def _dedupe_key(*, producer: str, symbol: str, ts: datetime) -> str:
    """Deterministic dedupe key: event-type + producer + symbol + epoch-seconds."""

    return f"{EventType.SIGNAL_PRICE_WS_V1}:{producer}:{symbol}:{int(ts.timestamp())}"


@register("price-alerts", domain="technical")
class PriceAlertsProducer(BaseProducer):
    """Polling producer that mimics a websocket price feed."""

    schedule = "*/1 * * * *"

    def _endpoint(self) -> str | None:
        return os.getenv("B1E55ED_PRICE_WS_URL") or os.getenv("PRICE_WS_URL")

    def collect(self) -> list[dict[str, Any]]:
        url = self._endpoint()
        if not url:
            self.ctx.logger.warning("price_ws_endpoint_missing")
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

            payload_obj = PriceWSSignalPayload(
                symbol=sym,
                price=row.get("price") or row.get("last") or row.get("last_price"),
                bid=row.get("bid"),
                ask=row.get("ask"),
                venue=row.get("venue") or row.get("exchange"),
            )
            payload = payload_obj.model_dump(mode="json")
            out.append(
                self.draft_event(
                    event_type=EventType.SIGNAL_PRICE_WS_V1,
                    payload=payload,
                    ts=ts,
                    observed_at=ts,
                    source=self.name,
                    dedupe_key=_dedupe_key(producer=self.name, symbol=sym, ts=ts),
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
            self.ctx.logger.exception("price_ws_run_failed")

        duration_ms = int((time.perf_counter() - start) * 1000)
        return ProducerResult(
            events_published=published,
            errors=errors,
            duration_ms=duration_ms,
            timestamp=datetime.now(tz=UTC),
            staleness_ms=None,
            health=health,
        )
