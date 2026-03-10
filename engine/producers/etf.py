"""engine.producers.etf

ETF Flows Producer.

Fetches ETF flow metrics (typically for BTC/ETH spot ETFs) from a configured
HTTP endpoint and emits :class:`~engine.core.events.EventType.SIGNAL_ETF_V1`.

No reliable free API exists for ETF flows — requires B1E55ED_ETF_FLOWS_URL.
When unconfigured, the producer reports OK with zero events (not DEGRADED).

Easter egg:
- Even in an index, someone chose the weights.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from typing import Any

import httpx

from engine.core.events import ETFFlowPayload, EventType
from engine.core.models import Event
from engine.core.types import ProducerHealth, ProducerResult
from engine.producers.base import BaseProducer
from engine.producers.registry import register


def _dedupe_key(*, producer: str, symbol: str, ts: datetime) -> str:
    """Symbol + timestamp (+ producer) dedupe key."""

    return f"{EventType.SIGNAL_ETF_V1}:{producer}:{symbol}:{int(ts.timestamp())}"


@register("etf-flows", domain="tradfi")
class ETFFlowsProducer(BaseProducer):
    """Produce ETF flow signals for the configured universe."""

    schedule = "0 */1 * * *"  # hourly
    mcp_source_url: str | None = None  # override with MCP server URL when available

    # Settings discovery — the settings page reads these
    configurable_fields = [
        {
            "key": "B1E55ED_ETF_FLOWS_URL",
            "label": "ETF flows data endpoint",
            "type": "url",
            "required": True,
            "description": "Required — no free source available. Provide a URL that returns ETF flow data.",
        },
    ]

    def _custom_endpoint(self) -> str | None:
        """Optional custom/paid data endpoint override."""
        return os.getenv("B1E55ED_ETF_FLOWS_URL") or os.getenv("ETF_FLOWS_URL")

    def collect(self) -> list[dict[str, Any]]:
        url = self._custom_endpoint()
        if not url:
            self.ctx.logger.info("etf-flows requires B1E55ED_ETF_FLOWS_URL — no free source available")
            return []

        symbols = [s.upper().strip() for s in self.ctx.config.universe.symbols]
        data: Any = asyncio.run(self.ctx.client.request_json("POST", url, expected=(list, dict), json={"symbols": symbols}))
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

            payload_obj = ETFFlowPayload(
                symbol=sym,
                daily_flow_usd=row.get("daily_flow_usd"),
                streak_days=int(row.get("streak_days") or 0),
                cumulative_7d=row.get("cumulative_7d"),
            )
            payload = payload_obj.model_dump(mode="json")
            out.append(
                self.draft_event(
                    event_type=EventType.SIGNAL_ETF_V1,
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
                if not self._custom_endpoint():
                    # No source configured — this is expected, not degraded
                    health = ProducerHealth.OK
                    errors.append("no_source_configured")
                else:
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
            self.ctx.logger.exception("etf_flows_run_failed")

        duration_ms = int((time.perf_counter() - start) * 1000)
        return ProducerResult(
            events_published=published,
            errors=errors,
            duration_ms=duration_ms,
            timestamp=datetime.now(tz=UTC),
            staleness_ms=None,
            health=health,
        )
