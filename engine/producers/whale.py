"""engine.producers.whale

Whale Tracking Producer.

Tracks large-holder / smart-money metrics via a configured endpoint and emits
:class:`~engine.core.events.EventType.SIGNAL_WHALE_V1`.

Free fallback uses the Binance public trades API (no auth required) to detect
large trades as a proxy for whale activity when no custom endpoint is configured.

Easter egg:
- Follow the whales if you must; follow the truth even when it's quieter.
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

from engine.core.events import EventType, WhaleSignalPayload
from engine.core.models import Event
from engine.core.types import ProducerHealth, ProducerResult
from engine.producers.base import BaseProducer
from engine.producers.registry import register

# Minimum trade value in USD to count as "whale"
_WHALE_THRESHOLD_USD = 50_000


def _dedupe_key(*, producer: str, symbol: str, ts: datetime) -> str:
    return f"{EventType.SIGNAL_WHALE_V1}:{producer}:{symbol}:{int(ts.timestamp())}"


@register("whale-tracking", domain="onchain")
class WhaleTrackingProducer(BaseProducer):
    schedule = "*/30 * * * *"
    mcp_source_url: str | None = None  # override with MCP server URL when available

    # Settings discovery — the settings page reads these
    configurable_fields = [
        {
            "key": "B1E55ED_WHALE_TRACKING_URL",
            "label": "Custom whale tracking endpoint",
            "type": "url",
            "required": False,
            "description": "Override the free Binance fallback with a custom whale tracking service",
        },
    ]

    def _custom_endpoint(self) -> str | None:
        """Optional custom/paid data endpoint override."""
        return os.getenv("B1E55ED_WHALE_TRACKING_URL") or os.getenv("WHALE_TRACKING_URL")

    def _collect_from_custom(self, url: str) -> list[dict[str, Any]]:
        """Fetch from a custom POST endpoint (original behaviour)."""
        symbols = [s.upper().strip() for s in self.ctx.config.universe.symbols]
        data: Any = asyncio.run(self.ctx.client.request_json("POST", url, expected=(list, dict), json={"symbols": symbols}))
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        if not isinstance(data, list):
            return []
        return [row for row in data if isinstance(row, dict)]

    def _collect_free(self) -> list[dict[str, Any]]:
        """Free public API fallback — Binance recent trades. No auth required.

        Fetches the 1000 most recent trades for each symbol, filters for large
        trades (>$50k), and computes a net buy/sell ratio as a proxy for
        smart_money_netflow.
        """
        symbols = [s.upper().strip() for s in self.ctx.config.universe.symbols]
        results: list[dict[str, Any]] = []

        for sym in symbols[:10]:  # limit to avoid rate limits
            try:
                resp = httpx.get(
                    "https://api.binance.com/api/v3/trades",
                    params={"symbol": f"{sym}USDT", "limit": 1000},
                    timeout=10.0,
                )
                resp.raise_for_status()
                trades = resp.json()

                if not isinstance(trades, list) or not trades:
                    continue

                # Filter for large trades
                whale_buys_usd = 0.0
                whale_sells_usd = 0.0
                whale_trade_count = 0

                for trade in trades:
                    try:
                        price = float(trade.get("price", 0))
                        qty = float(trade.get("qty", 0))
                        value_usd = price * qty
                        is_buyer_maker = trade.get("isBuyerMaker", False)

                        if value_usd >= _WHALE_THRESHOLD_USD:
                            whale_trade_count += 1
                            if is_buyer_maker:
                                # Buyer is maker = sell aggressor hit the bid
                                whale_sells_usd += value_usd
                            else:
                                # Buyer is taker = buy aggressor lifted the ask
                                whale_buys_usd += value_usd
                    except (TypeError, ValueError):
                        continue

                # Net flow: positive = net buying, negative = net selling
                netflow = whale_buys_usd - whale_sells_usd

                # Normalize netflow to a -1..1 scale (rough)
                total = whale_buys_usd + whale_sells_usd
                normalized_netflow = (netflow / total) if total > 0 else 0.0

                results.append(
                    {
                        "symbol": sym,
                        "smart_money_netflow": round(normalized_netflow, 4),
                        "top_holders_change": None,  # not available from trades API
                        "whale_trade_count": whale_trade_count,
                        "whale_volume_usd": round(total, 2),
                        "data_source": "binance_free",
                    }
                )
            except Exception as e:  # noqa: BLE001
                self.ctx.logger.warning("whale_free_symbol_failed symbol=%s error=%s", sym, e)
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

            payload_obj = WhaleSignalPayload(
                symbol=sym,
                smart_money_netflow=row.get("smart_money_netflow"),
                top_holders_change=row.get("top_holders_change"),
            )
            payload = payload_obj.model_dump(mode="json")
            out.append(
                self.draft_event(
                    event_type=EventType.SIGNAL_WHALE_V1,
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
            self.ctx.logger.exception("whale_tracking_run_failed")

        duration_ms = int((time.perf_counter() - start) * 1000)
        return ProducerResult(
            events_published=published,
            errors=errors,
            duration_ms=duration_ms,
            timestamp=datetime.now(tz=UTC),
            staleness_ms=None,
            health=health,
        )
