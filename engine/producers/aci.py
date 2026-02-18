"""engine.producers.aci

AI Consensus Index (ACI) Producer.

Treats the configured endpoint as an inference API (LLM or an ensemble service)
that returns a consensus score per symbol.

It emits :class:`~engine.core.events.EventType.SIGNAL_ACI_V1`.

The endpoint is configured via env and tests mock the injected
``context.client``.

Easter egg (timeless):
- Consensus is a mirror; mirrors don't care who is looking.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from engine.core.events import ACISignalPayload, EventType, payload_hash
from engine.core.models import Event
from engine.core.types import ProducerHealth, ProducerResult
from engine.producers.base import BaseProducer
from engine.producers.registry import register


_INT_RE = re.compile(r"[-+]?\d+")


def parse_score(value: Any) -> int:
    """Extract the last integer from a model response and clamp to [-10, 10].

    The upstream endpoint is allowed to be messy (LLM text, JSON wrapper, etc.).
    Contract:
    - find the *last* integer in the response (handles "thinking" traces)
    - clamp to [-10, 10]
    - if nothing parseable exists, return 0
    """

    # Unwrap common JSON shapes
    if isinstance(value, dict):
        for k in ("score", "consensus_score", "consensus", "result", "response", "text", "content"):
            if k in value:
                return parse_score(value.get(k))
        return 0

    if value is None:
        return 0

    if isinstance(value, (int, float)):
        n = int(value)
        return max(-10, min(10, n))

    s = str(value)
    matches = _INT_RE.findall(s)
    if not matches:
        return 0

    try:
        n = int(matches[-1])
    except ValueError:
        return 0

    return max(-10, min(10, n))


def _dedupe_key(*, producer: str, payload: dict[str, Any]) -> str:
    """Deterministic dedupe key based on canonicalized payload."""

    return f"{EventType.SIGNAL_ACI_V1}:{producer}:{payload_hash(payload)}"


@register("ai-consensus", domain="curator")
class ACIProducer(BaseProducer):
    schedule = "*/30 * * * *"

    def _endpoint(self) -> str | None:
        return os.getenv("B1E55ED_ACI_URL") or os.getenv("ACI_URL")

    def collect(self) -> list[dict[str, Any]]:
        url = self._endpoint()
        if not url:
            self.ctx.logger.warning("aci_endpoint_missing")
            return []

        symbols = [s.upper().strip() for s in self.ctx.config.universe.symbols]
        resp = asyncio.run(self.ctx.client.request("POST", url, json={"symbols": symbols}))

        data: Any = resp.json()
        if isinstance(data, dict) and "data" in data:
            data = data["data"]

        # Supported shapes:
        # - list[dict]  -> already correct
        # - dict        -> treat as single row
        if isinstance(data, dict):
            return [data]
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

            score_raw = row.get("consensus_score")
            if score_raw is None:
                score_raw = row.get("score")
            if score_raw is None:
                score_raw = row.get("response") or row.get("text") or row.get("content")

            consensus = float(parse_score(score_raw))

            mq = row.get("models_queried")
            mr = row.get("models_responded")
            disp = row.get("dispersion")

            models_queried = int(mq) if isinstance(mq, int) else 1
            models_responded = int(mr) if isinstance(mr, int) else models_queried
            dispersion = float(disp) if isinstance(disp, (int, float)) else 0.0

            payload_obj = ACISignalPayload(
                symbol=sym,
                consensus_score=consensus,
                models_queried=models_queried,
                models_responded=models_responded,
                dispersion=dispersion,
            )
            payload = payload_obj.model_dump(mode="json")

            out.append(
                self.draft_event(
                    event_type=EventType.SIGNAL_ACI_V1,
                    payload=payload,
                    ts=ts,
                    observed_at=ts,
                    source=self.name,
                    dedupe_key=_dedupe_key(producer=self.name, payload=payload),
                )
            )

        return out

    def run(self) -> ProducerResult:
        """Run with producer isolation: never raise.

        401/403 are treated as a degraded state (misconfigured/expired creds).
        """

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
        except Exception as e:  # noqa: BLE001 - producer isolation boundary
            health = ProducerHealth.ERROR
            errors.append(f"{type(e).__name__}: {e}")
            self.ctx.logger.exception("aci_run_failed")

        duration_ms = int((time.perf_counter() - start) * 1000)
        return ProducerResult(
            events_published=published,
            errors=errors,
            duration_ms=duration_ms,
            timestamp=datetime.now(tz=UTC),
            staleness_ms=None,
            health=health,
        )
