"""engine.social.collectors.polymarket

Polymarket prediction-market sentiment via Gamma API (free, no auth).

Maps crypto prediction markets to symbols where possible.
"""

from __future__ import annotations

import contextlib
import logging
import re
from typing import Any

import httpx

from engine.social.collectors.base import BaseCollector

logger = logging.getLogger(__name__)

_GAMMA_URL = "https://gamma-api.polymarket.com/events"


class PolymarketCollector(BaseCollector):
    """Collect sentiment from Polymarket crypto prediction markets."""

    name = "polymarket"

    def collect(self, symbols: list[str]) -> list[dict[str, Any]]:
        try:
            resp = httpx.get(
                _GAMMA_URL,
                params={"tag": "crypto", "closed": "false", "limit": "50"},
                timeout=10,
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            events = resp.json()
        except Exception:
            logger.warning("polymarket_fetch_failed", exc_info=True)
            return []

        if not isinstance(events, list):
            return []

        sym_set = {s.upper() for s in symbols}
        results: list[dict[str, Any]] = []

        for event in events:
            title = event.get("title", "") or ""
            markets = event.get("markets", []) or []

            # Try to match symbols in the event title
            matched_syms = _match_symbols(title, sym_set)
            if not matched_syms:
                continue

            # Aggregate market probabilities as sentiment proxy
            # Higher "yes" probability on bullish markets ≈ positive sentiment
            probs: list[float] = []
            for mkt in markets:
                # outcomePrices is a JSON string like '["0.65","0.35"]'
                outcome_prices = mkt.get("outcomePrices")
                if isinstance(outcome_prices, str):
                    import json

                    with contextlib.suppress(ValueError, IndexError, json.JSONDecodeError):
                        prices = json.loads(outcome_prices)
                        if prices:
                            probs.append(float(prices[0]))
                elif isinstance(outcome_prices, list) and outcome_prices:
                    with contextlib.suppress(ValueError, IndexError):
                        probs.append(float(outcome_prices[0]))

            if not probs:
                continue

            avg_prob = sum(probs) / len(probs)
            # Map probability to sentiment: 0.5 → 0 (neutral), 1.0 → 1, 0.0 → -1
            sentiment = (avg_prob - 0.5) * 2

            for sym in matched_syms:
                results.append(
                    {
                        "symbol": sym,
                        "sentiment": round(sentiment, 4),
                        "source": self.name,
                        "volume": len(probs),
                    }
                )

        logger.info("polymarket_collected", extra={"events": len(events), "signals": len(results)})
        return results


def _match_symbols(text: str, sym_set: set[str]) -> list[str]:
    """Find which symbols from sym_set appear in text."""
    text_upper = text.upper()
    matched = []
    for sym in sym_set:
        # Match whole word: "BTC" but not "BTCX"
        if re.search(rf"\b{re.escape(sym)}\b", text_upper):
            matched.append(sym)
    # Also check common full names
    _name_map = {
        "BITCOIN": "BTC",
        "ETHEREUM": "ETH",
        "SOLANA": "SOL",
        "HYPERLIQUID": "HYPE",
    }
    for name, sym in _name_map.items():
        if name in text_upper and sym in sym_set and sym not in matched:
            matched.append(sym)

    return matched
