"""engine.producers.price_ws

Price Alerts Producer (polling placeholder).

This producer is intentionally implemented as a polling loop (HTTP request) even
though the intended long-term interface is a websocket price stream.

Free fallback uses the Binance Ticker public API (no auth required) when no
custom endpoint is configured.

It emits :class:`~engine.core.events.EventType.SIGNAL_PRICE_WS_V1` events.

Easter egg:
- There is no "real-time"—only smaller intervals.
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
    mcp_source_url: str | None = None  # override with MCP server URL when available

    # Settings discovery — the settings page reads these
    configurable_fields = [
        {
            "key": "B1E55ED_PRICE_WS_URL",
            "label": "Custom Price WS endpoint",
            "type": "url",
            "required": False,
            "description": "Override the free Binance fallback with a custom price data service",
        },
    ]

    def _custom_endpoint(self) -> str | None:
        """Optional custom/paid data endpoint override."""
        return os.getenv("B1E55ED_PRICE_WS_URL") or os.getenv("PRICE_WS_URL")

    def _get_active_symbols(self) -> list[str]:
        """Return full active symbol list (bundles + explicit), not just explicit symbols."""
        return self.ctx.config.universe.active_symbols()

    def _collect_from_custom(self, url: str) -> list[dict[str, Any]]:
        """Fetch from a custom POST endpoint (original behaviour)."""
        symbols = self._get_active_symbols()
        data: Any = asyncio.run(self.ctx.client.request_json("POST", url, expected=(list, dict), json={"symbols": symbols}))
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        if not isinstance(data, list):
            return []
        return [row for row in data if isinstance(row, dict)]

    _BINANCE_SKIP: dict[str, str] = {"HYPE": "hyperliquid"}

    def _collect_coingecko(self, symbol: str, cg_id: str) -> dict[str, Any] | None:
        try:
            resp = httpx.get("https://api.coingecko.com/api/v3/simple/price", params={"ids": cg_id, "vs_currencies": "usd"}, timeout=10.0)
            resp.raise_for_status()
            price = float(resp.json().get(cg_id, {}).get("usd", 0))
            if price > 0:
                return {"symbol": symbol, "price": price, "bid": price, "ask": price, "venue": "coingecko", "data_source": "coingecko_free"}
        except Exception as e:
            self.ctx.logger.warning("coingecko_fallback_failed symbol=%s error=%s", symbol, e)
        return None

    def _collect_free(self) -> list[dict[str, Any]]:
        """Free public API fallback (Binance Ticker). Always available."""
        symbols = self._get_active_symbols()
        results: list[dict[str, Any]] = []

        _cap = getattr(self.ctx.config.universe, "max_symbols", 0)
        _syms = symbols[:_cap] if _cap > 0 else symbols
        for sym in _syms:
            if sym in self._BINANCE_SKIP:
                row = self._collect_coingecko(sym, self._BINANCE_SKIP[sym])
                if row:
                    results.append(row)
                continue
            try:
                resp = httpx.get(
                    "https://api.binance.com/api/v3/ticker/24hr",
                    params={"symbol": f"{sym}USDT"},
                    timeout=10.0,
                )
                resp.raise_for_status()
                data = resp.json()

                results.append(
                    {
                        "symbol": sym,
                        "price": float(data.get("lastPrice", 0)),
                        "bid": float(data.get("bidPrice", 0)),
                        "ask": float(data.get("askPrice", 0)),
                        "venue": "binance",
                        "data_source": "binance_free",
                    }
                )
            except Exception as e:  # noqa: BLE001
                self.ctx.logger.warning("price_free_symbol_failed symbol=%s error=%s", sym, e)
                continue

        return results

    def collect(self) -> list[dict[str, Any]]:
        url = self._custom_endpoint()
        if url:
            try:
                return self._collect_from_custom(url)
            except Exception:  # noqa: BLE001
                self.ctx.logger.warning("custom_endpoint_failed_falling_back url=%s", url)
        # Fall back to free API
        return self._collect_free()

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
