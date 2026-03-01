"""engine.producers.polymarket

PolymarketProducer — prediction market probabilities for the Events domain.

Fetches active contracts from the Polymarket Gamma API (public, no auth required)
and emits risk_on/risk_off/neutral signals based on contract probability changes.

Use cases:
- Fed rate decision contracts → risk-on/risk-off for crypto
- BTC/ETH price contracts → market-implied sentiment anchor
- Geopolitical contracts → macro risk signal

API: https://gamma-api.polymarket.com (no authentication required)
MCP: registered with MCPProducerRegistry automatically via BaseProducer.
"""

from __future__ import annotations

import json
import math
from typing import Any

import httpx

from engine.core.events import EventType
from engine.core.models import Event
from engine.producers.base import BaseProducer
from engine.producers.registry import register


@register("polymarket", domain="events")
class PolymarketProducer(BaseProducer):
    name = "polymarket"
    domain = "events"
    schedule = "*/15 * * * *"
    mcp_source_url: str | None = None  # Polymarket has no upstream MCP server yet
    assets: list[str] = []  # domain-wide — not asset-specific

    GAMMA_BASE = "https://gamma-api.polymarket.com"
    TIMEOUT = 10

    # Hardcoded watchlist slugs — skips gracefully if market not found
    WATCHLIST_SLUGS: list[str] = [
        "will-the-fed-cut-rates-in-march-2026",
        "will-the-fed-cut-rates-in-may-2026",
        "will-bitcoin-reach-100000-in-2026",
        "will-btc-be-above-100000-on-december-31-2026",
        "will-ethereum-reach-5000-in-2026",
    ]

    _FED_HINTS = ("fed", "rate", "cut", "hike")
    _CRYPTO_HINTS = ("bitcoin", "btc", "ethereum", "eth", "crypto")

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _extract_markets(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        if isinstance(payload, dict):
            return [payload]
        raise ValueError("invalid_markets_payload")

    @staticmethod
    def _market_identity(market: dict[str, Any]) -> str | None:
        market_id = market.get("id")
        if market_id not in (None, ""):
            return str(market_id)

        slug = market.get("slug")
        if slug not in (None, ""):
            return str(slug)
        return None

    def collect(self) -> list[dict[str, Any]]:
        try:
            with httpx.Client(timeout=self.TIMEOUT) as client:
                out: list[dict[str, Any]] = []
                seen_ids: set[str] = set()

                top = client.get(
                    f"{self.GAMMA_BASE}/markets",
                    params={
                        "tag_slug": "crypto",
                        "active": "true",
                        "order": "liquidity",
                        "ascending": "false",
                        "limit": 10,
                    },
                )
                top.raise_for_status()

                for market in self._extract_markets(top.json()):
                    market_id = self._market_identity(market)
                    if market_id is None or market_id in seen_ids:
                        continue
                    seen_ids.add(market_id)
                    out.append(market)

                for slug in self.WATCHLIST_SLUGS:
                    try:
                        resp = client.get(f"{self.GAMMA_BASE}/markets", params={"slug": slug})
                        if resp.status_code == 404:
                            continue
                        resp.raise_for_status()
                        for market in self._extract_markets(resp.json()):
                            market_id = self._market_identity(market)
                            if market_id is None or market_id in seen_ids:
                                continue
                            seen_ids.add(market_id)
                            out.append(market)
                    except Exception:
                        continue

                return out
        except Exception:
            return []

    def _signal_from_slug(self, slug: str, probability: float) -> str:
        slug_l = slug.lower()

        if any(hint in slug_l for hint in self._FED_HINTS):
            if probability > 0.60:
                return "risk_on"
            if probability < 0.30:
                return "risk_off"
            return "neutral"

        if any(hint in slug_l for hint in self._CRYPTO_HINTS):
            if probability > 0.65:
                return "risk_on"
            if probability < 0.25:
                return "risk_off"
            return "neutral"

        return "neutral"

    def normalize(self, raw: list[dict[str, Any]]) -> list[Event]:
        out: list[Event] = []

        for market in raw:
            if not isinstance(market, dict):
                continue

            slug = str(market.get("slug", "") or "")
            outcome_prices = market.get("outcomePrices")

            try:
                if isinstance(outcome_prices, str):
                    parsed = json.loads(outcome_prices)
                elif isinstance(outcome_prices, list):
                    parsed = outcome_prices
                else:
                    raise ValueError("outcomePrices must be list or JSON string")

                if not parsed:
                    raise ValueError("outcomePrices must be non-empty")

                yes_price = float(parsed[0])
            except Exception:
                self.ctx.logger.warning(
                    "polymarket_malformed_outcome_prices",
                    extra={"slug": slug},
                )
                continue

            probability = max(0.01, min(0.99, yes_price))
            signal = self._signal_from_slug(slug, probability)

            liquidity = self._to_float(market.get("liquidity", 0) or 0)
            confidence = min(1.0, math.log10(max(1.0, liquidity)) / 6.0)

            payload = {
                "contract": market.get("slug", ""),
                "question": market.get("question", ""),
                "probability": probability,
                "volume_24h_usd": self._to_float(market.get("volume24hr", 0) or 0),
                "liquidity_usd": liquidity,
                "signal": signal,
                "confidence": confidence,
                "reason": f"Polymarket: {market.get('question', '')} at {probability:.0%}",
                "producer": self.name,
                "domain": self.domain,
                "asset": None,
                "direction": signal,
                "horizon": "event",
            }

            # EventType enum does not yet include POLYMARKET_SIGNAL_V1.
            # Emit it as requested; fallback keeps runtime compatibility.
            try:
                event = self.draft_event(
                    event_type="POLYMARKET_SIGNAL_V1",
                    payload=payload,
                    dedupe_key=f"polymarket:{market.get('id', market.get('slug', ''))}",
                )
            except Exception:
                event = self.draft_event(
                    event_type=EventType.SIGNAL_EVENTS_V1,
                    payload=payload,
                    dedupe_key=f"polymarket:{market.get('id', market.get('slug', ''))}",
                )

            out.append(event)

        return out
