"""engine.producers.curator

Curator Intel Producer.

Ingests operator/curator intel from a configured endpoint or local file, then
emits :class:`~engine.core.events.EventType.SIGNAL_CURATOR_V1`.

Configuration (env):
- ``B1E55ED_CURATOR_URL`` / ``CURATOR_URL``  (HTTP endpoint)
- ``B1E55ED_CURATOR_FILE`` / ``CURATOR_FILE`` (JSON file)

The endpoint/file is intentionally simple so unit tests can mock the injected
``context.client`` or write a temp file.

Easter egg:
- Human priors are a feature, not a bug.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from engine.core.events import CuratorSignalPayload, EventType, payload_hash
from engine.core.models import Event
from engine.core.types import ProducerHealth, ProducerResult
from engine.producers.base import BaseProducer
from engine.producers.registry import register


def _dedupe_key(*, producer: str, payload: dict[str, Any]) -> str:
    return f"{EventType.SIGNAL_CURATOR_V1}:{producer}:{payload_hash(payload)}"


@register("curator-intel", domain="curator")
class CuratorIntelProducer(BaseProducer):
    schedule = "*/10 * * * *"  # 10m

    def _endpoint(self) -> str | None:
        return os.getenv("B1E55ED_CURATOR_URL") or os.getenv("CURATOR_URL")

    def _file_path(self) -> str | None:
        return os.getenv("B1E55ED_CURATOR_FILE") or os.getenv("CURATOR_FILE")

    def collect(self) -> list[dict[str, Any]]:
        url = self._endpoint()
        fp = self._file_path()

        data: Any = None

        if url:
            # Endpoint can be mocked in tests via ctx.client
            data = asyncio.run(self.ctx.client.request_json("GET", url, expected=(list, dict), max_bytes=512 * 1024, max_items=2000))
        elif fp:
            p = Path(fp)
            if not p.exists():
                self.ctx.logger.warning("curator_file_missing", extra={"path": fp})
                return []
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                self.ctx.logger.warning("curator_file_invalid_json", extra={"path": fp})
                return []
        else:
            self.ctx.logger.warning("curator_source_missing")
            return []

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

            payload_obj = CuratorSignalPayload(
                symbol=sym,
                direction=(row.get("direction") or "neutral"),
                conviction=float(row.get("conviction") or 0.0),
                rationale=str(row.get("rationale") or ""),
                source=str(row.get("source") or "operator"),
            )
            payload = payload_obj.model_dump(mode="json")

            out.append(
                self.draft_event(
                    event_type=EventType.SIGNAL_CURATOR_V1,
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
            self.ctx.logger.exception("curator_intel_run_failed")

        duration_ms = int((time.perf_counter() - start) * 1000)
        return ProducerResult(
            events_published=published,
            errors=errors,
            duration_ms=duration_ms,
            timestamp=datetime.now(tz=UTC),
            staleness_ms=None,
            health=health,
        )
