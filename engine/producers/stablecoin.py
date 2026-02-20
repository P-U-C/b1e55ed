"""engine.producers.stablecoin

Stablecoin Supply Producer.

Pulls stablecoin supply deltas from a configured endpoint and emits
:class:`~engine.core.events.EventType.SIGNAL_STABLECOIN_V1`.

Endpoint is configured via env and is mocked in unit tests.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from engine.core.events import EventType, StablecoinSignalPayload
from engine.core.models import Event
from engine.core.types import ProducerHealth, ProducerResult
from engine.producers.base import BaseProducer
from engine.producers.registry import register


def _dedupe_key(*, producer: str, stablecoin: str, ts: datetime) -> str:
    return f"{EventType.SIGNAL_STABLECOIN_V1}:{producer}:{stablecoin}:{int(ts.timestamp())}"


@register("stablecoin-supply", domain="onchain")
class StablecoinSupplyProducer(BaseProducer):
    schedule = "0 */2 * * *"

    def _endpoint(self) -> str | None:
        return os.getenv("B1E55ED_STABLECOIN_SUPPLY_URL") or os.getenv("STABLECOIN_SUPPLY_URL")

    def collect(self) -> list[dict[str, Any]]:
        url = self._endpoint()
        if not url:
            self.ctx.logger.warning("stablecoin_supply_endpoint_missing")
            return []

        data: Any = asyncio.run(self.ctx.client.request_json("GET", url, expected=(list, dict)))
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        if not isinstance(data, list):
            return []
        return [row for row in data if isinstance(row, dict)]

    def normalize(self, raw: list[dict[str, Any]]) -> list[Event]:
        ts = datetime.now(tz=UTC)
        out: list[Event] = []

        for row in raw:
            sc = str(row.get("stablecoin") or row.get("symbol") or "").upper().strip()
            if not sc:
                continue

            payload_obj = StablecoinSignalPayload(
                stablecoin=sc,
                supply_change_24h=row.get("supply_change_24h"),
                supply_change_7d=row.get("supply_change_7d"),
                mint_burn_events=int(row.get("mint_burn_events") or 0),
            )
            payload = payload_obj.model_dump(mode="json")
            out.append(
                self.draft_event(
                    event_type=EventType.SIGNAL_STABLECOIN_V1,
                    payload=payload,
                    ts=ts,
                    observed_at=ts,
                    source=self.name,
                    dedupe_key=_dedupe_key(producer=self.name, stablecoin=sc, ts=ts),
                )
            )

        return out

    def run(self) -> ProducerResult:
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
            self.ctx.logger.exception("stablecoin_supply_run_failed")

        duration_ms = int((time.perf_counter() - start) * 1000)
        return ProducerResult(
            events_published=published,
            errors=errors,
            duration_ms=duration_ms,
            timestamp=datetime.now(tz=UTC),
            staleness_ms=None,
            health=health,
        )
