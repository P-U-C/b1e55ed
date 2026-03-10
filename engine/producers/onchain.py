"""engine.producers.onchain

Onchain Flows Producer.

Fetches flow-style metrics from a configured HTTP endpoint and emits
:class:`~engine.core.events.EventType.SIGNAL_ONCHAIN_V1`.

Depends on Allium API (subscription required). No free fallback available.
When unconfigured, the producer reports OK with zero events (not DEGRADED).

Easter egg:
- Flows are the river; truth is the delta.
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

from engine.core.events import EventType, OnchainSignalPayload
from engine.core.horizons import ONCHAIN_HORIZONS
from engine.core.models import Event
from engine.core.types import ProducerHealth, ProducerResult
from engine.producers.base import BaseProducer
from engine.producers.registry import register


def _dedupe_key(*, producer: str, symbol: str, ts: datetime) -> str:
    """Symbol + timestamp (+ producer) dedupe key."""

    return f"{EventType.SIGNAL_ONCHAIN_V1}:{producer}:{symbol}:{int(ts.timestamp())}"


@register("onchain-flows", domain="onchain")
class OnchainFlowsProducer(BaseProducer):
    schedule = "*/30 * * * *"
    mcp_source_url: str | None = None  # override with MCP server URL when available

    # Settings discovery — the settings page reads these
    configurable_fields = [
        {
            "key": "B1E55ED_ONCHAIN_FLOWS_URL",
            "label": "Onchain flows data endpoint",
            "type": "url",
            "required": True,
            "description": "Required — depends on Allium API (subscription). Provide your Allium-backed endpoint URL.",
        },
        {
            "key": "ALLIUM_API_KEY",
            "label": "Allium API key",
            "type": "secret",
            "required": True,
            "description": "API key for the Allium on-chain data platform (allium.so).",
        },
    ]

    def _custom_endpoint(self) -> str | None:
        """Optional custom/paid data endpoint override."""
        return os.getenv("B1E55ED_ONCHAIN_FLOWS_URL") or os.getenv("ONCHAIN_FLOWS_URL")

    def collect(self) -> list[dict[str, Any]]:
        url = self._custom_endpoint()
        if not url:
            self.ctx.logger.info("onchain-flows requires B1E55ED_ONCHAIN_FLOWS_URL (Allium API) — no free source available")
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

            exchange_flow = row.get("exchange_flow")
            flow_direction: str | None = None
            flow_magnitude: float | None = None
            if exchange_flow is not None:
                try:
                    ef = float(exchange_flow)
                except (TypeError, ValueError):
                    ef = 0.0
                if ef > 1_000_000:
                    flow_direction = "inflow"
                elif ef < -1_000_000:
                    flow_direction = "outflow"
                else:
                    flow_direction = "neutral"
                flow_magnitude = round(min(abs(ef) / 50_000_000, 1.0), 3)

            payload_obj = OnchainSignalPayload(
                symbol=sym,
                whale_netflow=row.get("whale_netflow"),
                exchange_flow=exchange_flow,
                active_addresses_change=row.get("active_addresses_change"),
                price_momentum_24h=row.get("price_momentum_24h"),
                flow_direction=flow_direction,
                flow_magnitude=flow_magnitude,
                entity_type=row.get("entity_type"),
            )
            payload = payload_obj.model_dump(mode="json")
            out.append(
                self.draft_event(
                    event_type=EventType.SIGNAL_ONCHAIN_V1,
                    payload=payload,
                    ts=ts,
                    observed_at=ts,
                    source=self.name,
                    dedupe_key=_dedupe_key(producer=self.name, symbol=sym, ts=ts),
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
                if not self._custom_endpoint():
                    # No source configured — this is expected, not degraded
                    health = ProducerHealth.OK
                    errors.append("no_source_configured")
                else:
                    health = ProducerHealth.DEGRADED
            events = self.normalize(raw)
            published = self.publish(events)

            symbols = [s.upper().strip() for s in self.ctx.config.universe.symbols]
            signal_payloads = [e.payload for e in events]
            for symbol in symbols:
                self.emit_forecasts_multi_horizon(
                    asset=symbol,
                    signals=signal_payloads,
                    regime_tag="unknown",
                    visible_signal_refs=[],
                    horizon_configs=ONCHAIN_HORIZONS,
                )
        except httpx.HTTPStatusError as e:
            code = getattr(e.response, "status_code", None)
            health = ProducerHealth.DEGRADED if code in (401, 403) else ProducerHealth.ERROR
            errors.append(f"HTTPStatusError: {code}")
        except Exception as e:  # noqa: BLE001
            health = ProducerHealth.ERROR
            errors.append(f"{type(e).__name__}: {e}")
            self.ctx.logger.exception("onchain_flows_run_failed")

        duration_ms = int((time.perf_counter() - start) * 1000)
        return ProducerResult(
            events_published=published,
            errors=errors,
            duration_ms=duration_ms,
            timestamp=datetime.now(tz=UTC),
            staleness_ms=None,
            health=health,
        )
