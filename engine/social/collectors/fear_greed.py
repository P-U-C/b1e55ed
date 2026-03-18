"""engine.social.collectors.fear_greed

Fear & Greed Index collector via alternative.me (free, no auth).

Maps market-wide sentiment to all symbols in universe.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from engine.social.collectors.base import BaseCollector

logger = logging.getLogger(__name__)

_FNG_URL = "https://api.alternative.me/fng/?limit=1"


class FearGreedCollector(BaseCollector):
    """Collect Fear & Greed Index — market-wide sentiment proxy."""

    name = "fear_greed"

    def collect(self, symbols: list[str]) -> list[dict[str, Any]]:
        try:
            resp = httpx.get(_FNG_URL, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.warning("fear_greed_fetch_failed", exc_info=True)
            return []

        entries = data.get("data")
        if not entries or not isinstance(entries, list):
            logger.warning("fear_greed_empty_response")
            return []

        raw_value = entries[0].get("value")
        if raw_value is None:
            return []

        # FNG is 0-100.  Map to -1..1 sentiment: 0 → -1 (extreme fear), 100 → 1 (extreme greed)
        fng_int = int(raw_value)
        sentiment = (fng_int - 50) / 50  # 0→-1, 50→0, 100→1

        results: list[dict[str, Any]] = []
        for sym in symbols:
            results.append(
                {
                    "symbol": sym.upper(),
                    "sentiment": round(sentiment, 4),
                    "source": self.name,
                    "volume": 1,  # single market-wide reading
                }
            )

        logger.info("fear_greed_collected", extra={"fng": fng_int, "sentiment": sentiment, "symbols": len(results)})
        return results
