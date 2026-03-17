"""engine.producers.aci

AI Consensus Index (ACI) Producer.

Treats the configured endpoint as an inference API (LLM or an ensemble service)
that returns a consensus score per symbol.

It emits :class:`~engine.core.events.EventType.SIGNAL_ACI_V1`.

Data sources (tried in order):
1. Custom ACI_URL endpoint — any service returning per-symbol consensus scores
2. Kaito AI (KAITO_API_KEY) — xmind narrative intelligence, real-time CT scoring
3. Token Metrics (TOKEN_METRICS_API_KEY) — AI-driven crypto grades
4. No source → reports OK with zero events (not DEGRADED)

Design note: Generic LLMs (GPT, Claude, Grok, Perplexity) are intentionally
NOT supported. They lack real-time market data and produce noise not edge.
This producer only fires when it has proprietary crypto-native signal.

Easter egg (timeless):
- Consensus is a mirror; mirrors don't care who is looking.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

import logging
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
    mcp_source_url: str | None = None  # override with MCP server URL when available

    def _endpoint(self) -> str | None:
        return os.getenv("B1E55ED_ACI_URL") or os.getenv("ACI_URL")

    def _has_any_source(self) -> bool:
        """True if any configured source is available."""
        return bool(self._endpoint() or os.getenv("KAITO_API_KEY") or os.getenv("TOKEN_METRICS_API_KEY"))

    def _collect_kaito(self) -> list[dict[str, Any]]:
        """Kaito AI narrative intelligence — xmind CT scoring.

        Requires KAITO_API_KEY. Returns per-symbol consensus scores derived
        from real-time Crypto Twitter narrative analysis.

        # TODO: wire Kaito API once endpoint spec is confirmed
        # Placeholder endpoint: https://api.kaito.ai/api/v1/ai-consensus
        # Docs: https://kaito.ai — contact for API access
        """
        api_key = os.getenv("KAITO_API_KEY")
        if not api_key:
            return []

        _log = logging.getLogger(__name__)
        _log.info("kaito_aci_stub: KAITO_API_KEY set but integration not yet wired")
        # TODO: wire Kaito API
        return []

    def _collect_token_metrics(self) -> list[dict[str, Any]]:
        """Token Metrics AI grades — quantitative crypto scoring.

        Requires TOKEN_METRICS_API_KEY. Returns per-token AI grade mapped
        to the [-10, 10] consensus score range.

        # TODO: wire Token Metrics API once grades endpoint is validated
        # Endpoint: https://api.tokenmetrics.com/v2/tokens
        # Docs: https://tokenmetrics.com — free tier available
        """
        api_key = os.getenv("TOKEN_METRICS_API_KEY")
        if not api_key:
            return []

        _log = logging.getLogger(__name__)
        _log.info("token_metrics_aci_stub: TOKEN_METRICS_API_KEY set but integration not yet wired")
        # TODO: wire Token Metrics API
        return []

    def collect(self) -> list[dict[str, Any]]:
        # 1. Custom ACI endpoint
        url = self._endpoint()
        if url:
            symbols = [s.upper().strip() for s in self.ctx.config.universe.symbols]
            data: Any = asyncio.run(
                self.ctx.client.request_json(
                    "POST",
                    url,
                    expected=(list, dict),
                    json={"symbols": symbols},
                    max_bytes=1024 * 1024,
                    max_items=2000,
                )
            )
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

        # 2. Kaito AI
        kaito_data = self._collect_kaito()
        if kaito_data:
            return kaito_data

        # 3. Token Metrics
        tm_data = self._collect_token_metrics()
        if tm_data:
            return tm_data

        # 4. No source available
        self.ctx.logger.info("ai_consensus_no_source_configured")
        return []

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
        When no source is configured, return OK with a note — not an error.
        This producer is intentionally silent rather than noisy: generic LLMs
        are not used as fallbacks because they lack real-time market edge.
        """

        start = time.perf_counter()
        errors: list[str] = []
        published = 0
        health: ProducerHealth = ProducerHealth.OK

        # Graceful skip when no source is configured
        if not self._has_any_source():
            duration_ms = int((time.perf_counter() - start) * 1000)
            return ProducerResult(
                events_published=0,
                errors=["no_source_configured: set ACI_URL, KAITO_API_KEY, or TOKEN_METRICS_API_KEY"],
                duration_ms=duration_ms,
                timestamp=datetime.now(tz=UTC),
                staleness_ms=None,
                health=ProducerHealth.OK,
            )

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
