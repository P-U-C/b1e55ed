"""engine.producers.social

Social Intel Producer.

Delegates to :mod:`engine.social.pipeline` to collect and score social data,
then emits :class:`~engine.core.events.EventType.SIGNAL_SOCIAL_V1`.

The social pipeline is intentionally isolated behind a single call so tests can
mock it easily.

Easter egg:
- Social is the memetic surface of positioning.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import httpx

from engine.core.events import EventType, SocialSignalPayload, payload_hash
from engine.core.models import Event
from engine.core.types import ProducerHealth, ProducerResult
from engine.producers.base import BaseProducer
from engine.producers.registry import register
from engine.social import pipeline


def _dedupe_key(*, producer: str, payload: dict[str, Any]) -> str:
    return f"{EventType.SIGNAL_SOCIAL_V1}:{producer}:{payload_hash(payload)}"


@register("social-intel", domain="social")
class SocialIntelProducer(BaseProducer):
    schedule = "*/15 * * * *"  # 15m

    def collect(self) -> list[dict[str, Any]]:
        rows = pipeline.run(ctx=self.ctx)
        if not isinstance(rows, list):
            return []
        return [r for r in rows if isinstance(r, dict)]

    def normalize(self, raw: list[dict[str, Any]]) -> list[Event]:
        ts = datetime.now(tz=UTC)
        out: list[Event] = []

        for row in raw:
            sym = str(row.get("symbol") or row.get("asset") or "").upper().strip()
            if not sym:
                continue

            payload_obj = SocialSignalPayload(
                symbol=sym,
                score=float(row.get("score")) if row.get("score") is not None else 0.0,
                direction=(row.get("direction") or "neutral"),
                source_count=int(row.get("source_count") or 0),
                contrarian_flag=bool(row.get("contrarian_flag") or False),
                echo_chamber_flag=bool(row.get("echo_chamber_flag") or False),
            )
            payload = payload_obj.model_dump(mode="json")

            out.append(
                self.draft_event(
                    event_type=EventType.SIGNAL_SOCIAL_V1,
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
            self.ctx.logger.exception("social_intel_run_failed")

        duration_ms = int((time.perf_counter() - start) * 1000)
        return ProducerResult(
            events_published=published,
            errors=errors,
            duration_ms=duration_ms,
            timestamp=datetime.now(tz=UTC),
            staleness_ms=None,
            health=health,
        )
