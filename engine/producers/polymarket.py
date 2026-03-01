"""engine.producers.polymarket

Polymarket prediction-market producer for the events domain.

Collects:
- Curated watchlist markets by slug
- Top liquid active crypto markets

Normalizes market probabilities into risk_on / risk_off / neutral events.
"""

from __future__ import annotations

import json
import math
from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    UTC = UTC  # noqa: N806

from typing import Any

import httpx

from engine.core.events import EventType
from engine.core.models import Event
from engine.producers.base import BaseProducer
from engine.producers.registry import register

GAMMA_API_BASE = "https://gamma-api.polymarket.com"

WATCHLIST_SLUGS = [
    # Macro / Fed
    "will-the-fed-cut-rates-in-march-2026",
    "will-the-fed-cut-rates-in-may-2026",
    "federal-reserve-rate-cut-2026",
    # Crypto price
    "will-bitcoin-reach-100000-in-2026",
    "will-btc-be-above-100000-on-december-31-2026",
    "will-ethereum-reach-5000-in-2026",
    # Geopolitical: fetched dynamically via tags in future iterations.
]


@register("polymarket", domain="events")
class PolymarketProducer(BaseProducer):
    """Prediction-market signal producer using Polymarket's public Gamma API."""

    name = "polymarket"
    domain = "events"
    schedule = "*/15 * * * *"
    mcp_source_url: str | None = None
    assets: list[str] = []

    _api_base = GAMMA_API_BASE

    @staticmethod
    def _as_markets(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
            return [payload]
        return []

    @staticmethod
    def _to_float(value: Any, *, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _parse_yes_probability(outcome_prices: Any) -> float:
        parsed: Any = outcome_prices
        if isinstance(outcome_prices, str):
            parsed = json.loads(outcome_prices)

        if not isinstance(parsed, list) or not parsed:
            raise ValueError("outcomePrices missing or malformed")

        return float(parsed[0])

    def collect(self) -> list[dict[str, Any]]:
        """Collect polymarket market dicts.

        Never raises: returns [] on any error.
        """

        try:
            collected: list[dict[str, Any]] = []
            with httpx.Client(timeout=10.0) as client:
                for slug in WATCHLIST_SLUGS:
                    resp = client.get(
                        f"{self._api_base}/markets",
                        params={"slug": slug},
                        timeout=10.0,
                    )
                    if resp.status_code == 404:
                        continue
                    resp.raise_for_status()
                    collected.extend(self._as_markets(resp.json()))

                top_crypto = client.get(
                    f"{self._api_base}/markets",
                    params={
                        "tag_slug": "crypto",
                        "active": "true",
                        "order": "liquidity",
                        "ascending": "false",
                        "limit": 10,
                    },
                    timeout=10.0,
                )
                top_crypto.raise_for_status()
                collected.extend(self._as_markets(top_crypto.json()))

            deduped: dict[str, dict[str, Any]] = {}
            for market in collected:
                market_id = str(market.get("id") or "").strip()
                if market_id:
                    deduped[market_id] = market
                    continue

                # Fallback if id is missing.
                slug = str(market.get("slug") or "").strip()
                if slug:
                    deduped[f"slug:{slug}"] = market

            return list(deduped.values())
        except Exception:  # noqa: BLE001
            return []

    def normalize(self, raw: list[dict[str, Any]]) -> list[Event]:
        """Normalize market dicts into Event envelopes.

        Never raises: malformed rows are skipped silently.
        """

        try:
            ts = datetime.now(tz=UTC)
            events: list[Event] = []

            for market in raw:
                try:
                    slug = str(market.get("slug") or "").strip()
                    question = str(market.get("question") or "").strip()
                    if not slug or not question:
                        continue

                    probability = self._parse_yes_probability(market.get("outcomePrices"))
                    slug_lower = slug.lower()

                    signal = "neutral"
                    if any(token in slug_lower for token in ("fed", "rate", "cut")):
                        if probability > 0.6:
                            signal = "risk_on"
                        elif probability < 0.3:
                            signal = "risk_off"
                    elif any(token in slug_lower for token in ("bitcoin", "btc", "ethereum", "eth")):
                        if probability > 0.65:
                            signal = "risk_on"

                    liquidity = self._to_float(market.get("liquidity", 0), default=0.0)
                    confidence = min(1.0, math.log10(max(1.0, liquidity)) / 6)

                    payload = {
                        "contract": slug,
                        "question": question,
                        "probability": probability,
                        "volume_24h_usd": market.get("volume24hr", 0),
                        "liquidity_usd": market.get("liquidity", 0),
                        "signal": signal,
                        "confidence": confidence,
                        "reason": f"Polymarket: {question} at {probability:.0%}",
                        "producer": "polymarket",
                        "domain": "events",
                    }

                    events.append(
                        self.draft_event(
                            event_type=EventType.SIGNAL_EVENTS_V1,
                            payload=payload,
                            ts=ts,
                            observed_at=ts,
                            source=self.name,
                            dedupe_key=f"{EventType.SIGNAL_EVENTS_V1}:{self.name}:{slug}:{int(ts.timestamp())}",
                        )
                    )
                except Exception:  # noqa: BLE001
                    continue

            return events
        except Exception:  # noqa: BLE001
            return []
