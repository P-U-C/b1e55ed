"""engine.producers.etf

ETF Flows Producer.

Fetches ETF flow metrics (typically for BTC/ETH spot ETFs) from a configured
HTTP endpoint or the Coinglass v4 API, and emits
:class:`~engine.core.events.EventType.SIGNAL_ETF_V1`.

Data sources (tried in order):
1. Custom endpoint (B1E55ED_ETF_FLOWS_URL) — any URL that returns flow data
2. Coinglass v4 API (COINGLASS_API_KEY) — free tier at coinglass.com
3. No source → reports OK with zero events (not DEGRADED)

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

import logging
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
            "label": "Custom ETF flows endpoint",
            "type": "url",
            "required": False,
            "description": "Custom HTTP endpoint for ETF flow data",
        },
        {
            "key": "COINGLASS_API_KEY",
            "label": "Coinglass API Key",
            "type": "secret",
            "required": False,
            "description": "Free tier available at coinglass.com — enables BTC/ETH ETF flow tracking",
        },
    ]

    def _custom_endpoint(self) -> str | None:
        """Optional custom/paid data endpoint override."""
        return os.getenv("B1E55ED_ETF_FLOWS_URL") or os.getenv("ETF_FLOWS_URL")

    def _collect_coinglass(self) -> list[dict[str, Any]]:
        """Fetch ETF flows from Coinglass v4 API (requires API key)."""
        api_key = os.getenv("COINGLASS_API_KEY")
        if not api_key:
            return []

        _log = logging.getLogger(__name__)
        results: list[dict[str, Any]] = []

        for asset in ["bitcoin", "ethereum"]:
            try:
                resp = httpx.get(
                    f"https://open-api-v4.coinglass.com/api/etf/{asset}/flow-history",
                    headers={"CG-API-KEY": api_key, "User-Agent": "b1e55ed/1.0"},
                    params={"limit": 7},
                    timeout=10.0,
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") == "0" and data.get("data"):
                    for day in data["data"]:
                        results.append(
                            {
                                "symbol": "BTC" if asset == "bitcoin" else "ETH",
                                "date": day.get("date", ""),
                                "total_net_flow_usd": float(day.get("totalNetFlow", 0)),
                                "price": float(day.get("price", 0)),
                                "etf_flows": day.get("flows", []),
                                "data_source": "coinglass",
                            }
                        )
            except Exception as e:  # noqa: BLE001
                _log.warning("coinglass_etf_failed: %s %s", asset, e)

        return results

    def collect(self) -> list[dict[str, Any]]:
        # 1. Try custom endpoint first
        url = self._custom_endpoint()
        if url:
            try:
                symbols = [s.upper().strip() for s in self.ctx.config.universe.symbols]
                data: Any = asyncio.run(
                    self.ctx.client.request_json(
                        "POST",
                        url,
                        expected=(list, dict),
                        json={"symbols": symbols},
                    )
                )
                if isinstance(data, dict) and "data" in data:
                    data = data["data"]
                if isinstance(data, list):
                    rows = [row for row in data if isinstance(row, dict)]
                    if rows:
                        return rows
            except Exception:  # noqa: BLE001
                self.ctx.logger.warning("custom_etf_endpoint_failed")

        # 2. Try Coinglass
        coinglass_data = self._collect_coinglass()
        if coinglass_data:
            return coinglass_data

        # 3. No source available
        self.ctx.logger.info("etf_no_source_configured")
        return []

    def normalize(self, raw: list[dict[str, Any]]) -> list[Event]:
        ts = datetime.now(tz=UTC)
        out: list[Event] = []

        for row in raw:
            sym = str(row.get("symbol") or row.get("asset") or "").upper().strip()
            if not sym:
                continue

            payload_obj = ETFFlowPayload(
                symbol=sym,
                daily_flow_usd=row.get("daily_flow_usd") or row.get("total_net_flow_usd"),
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
                if not self._custom_endpoint() and not os.getenv("COINGLASS_API_KEY"):
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
