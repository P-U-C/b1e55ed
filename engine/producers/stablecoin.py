"""engine.producers.stablecoin

Stablecoin Supply Producer.

Pulls stablecoin supply deltas from a configured endpoint and emits
:class:`~engine.core.events.EventType.SIGNAL_STABLECOIN_V1`.

Free fallback uses the DefiLlama Stablecoins API (no auth required) to fetch
current stablecoin supply data when no custom endpoint is configured.

Easter egg:
- Stablecoins are boring until they're not.
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

from engine.core.events import EventType, StablecoinSignalPayload
from engine.core.models import Event
from engine.core.types import ProducerHealth, ProducerResult
from engine.producers.base import BaseProducer
from engine.producers.registry import register


def _dedupe_key(*, producer: str, stablecoin: str, ts: datetime) -> str:
    return f"{EventType.SIGNAL_STABLECOIN_V1}:{producer}:{stablecoin}:{int(ts.timestamp())}"


# Major stablecoins we care about
_TRACKED_STABLES = {"USDT", "USDC", "DAI", "BUSD", "TUSD", "FRAX", "USDP", "USDD", "LUSD", "PYUSD", "GHO", "CUSD", "FDUSD"}


@register("stablecoin-supply", domain="onchain")
class StablecoinSupplyProducer(BaseProducer):
    schedule = "0 */2 * * *"
    mcp_source_url: str | None = None  # override with MCP server URL when available

    # Settings discovery — the settings page reads these
    configurable_fields = [
        {
            "key": "B1E55ED_STABLECOIN_SUPPLY_URL",
            "label": "Custom stablecoin supply endpoint",
            "type": "url",
            "required": False,
            "description": "Override the free DefiLlama fallback with a custom stablecoin data service",
        },
    ]

    def _custom_endpoint(self) -> str | None:
        """Optional custom/paid data endpoint override."""
        return os.getenv("B1E55ED_STABLECOIN_SUPPLY_URL") or os.getenv("STABLECOIN_SUPPLY_URL")

    def _collect_from_custom(self, url: str) -> list[dict[str, Any]]:
        """Fetch from a custom endpoint (original behaviour)."""
        data: Any = asyncio.run(self.ctx.client.request_json("GET", url, expected=(list, dict)))
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        if not isinstance(data, list):
            return []
        return [row for row in data if isinstance(row, dict)]

    def _collect_free(self) -> list[dict[str, Any]]:
        """Free public API fallback — DefiLlama Stablecoins. Always available, no auth.

        DefiLlama may return multiple entries per symbol (different chains/issuers).
        We keep only the largest by circulating supply to avoid dedupe conflicts.
        """
        try:
            resp = httpx.get(
                "https://stablecoins.llama.fi/stablecoins",
                params={"includePrices": "true"},
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()

            pegged_assets = data.get("peggedAssets", [])
            if not isinstance(pegged_assets, list):
                return []

            # Collect all entries, then deduplicate by symbol (keep largest)
            by_symbol: dict[str, dict[str, Any]] = {}

            for asset in pegged_assets:
                symbol = str(asset.get("symbol", "")).upper().strip()
                if not symbol or symbol not in _TRACKED_STABLES:
                    continue

                # Current circulating supply
                circulating = asset.get("circulating", {})
                current_supply = circulating.get("peggedUSD") if isinstance(circulating, dict) else None

                try:
                    current_val = float(current_supply) if current_supply is not None else 0.0
                except (TypeError, ValueError):
                    current_val = 0.0

                # Keep only the largest entry per symbol
                existing = by_symbol.get(symbol)
                if existing is not None and existing.get("_supply_val", 0.0) >= current_val:
                    continue

                # Supply changes from DefiLlama's chain data
                circ_prev_day = asset.get("circulatingPrevDay", {})
                circ_prev_week = asset.get("circulatingPrevWeek", {})

                supply_change_24h: float | None = None
                supply_change_7d: float | None = None

                if current_val > 0:
                    try:
                        if isinstance(circ_prev_day, dict):
                            prev_day_val = circ_prev_day.get("peggedUSD")
                            if prev_day_val is not None:
                                supply_change_24h = round(current_val - float(prev_day_val), 2)
                        if isinstance(circ_prev_week, dict):
                            prev_week_val = circ_prev_week.get("peggedUSD")
                            if prev_week_val is not None:
                                supply_change_7d = round(current_val - float(prev_week_val), 2)
                    except (TypeError, ValueError):
                        pass

                by_symbol[symbol] = {
                    "stablecoin": symbol,
                    "symbol": symbol,
                    "supply_change_24h": supply_change_24h,
                    "supply_change_7d": supply_change_7d,
                    "mint_burn_events": 0,
                    "data_source": "defillama_free",
                    "_supply_val": current_val,  # internal, not used by normalize
                }

            return list(by_symbol.values())
        except Exception as e:  # noqa: BLE001
            self.ctx.logger.warning("stablecoin_free_failed", extra={"error": str(e)})
            return []

    def collect(self) -> list[dict[str, Any]]:
        url = self._custom_endpoint()
        if url:
            try:
                return self._collect_from_custom(url)
            except Exception:  # noqa: BLE001
                self.ctx.logger.warning("custom_endpoint_failed_falling_back", extra={"url": url})
        # Fall back to free API
        return self._collect_free()

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
