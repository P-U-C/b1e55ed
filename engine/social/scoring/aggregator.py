"""engine.social.scoring.aggregator

Aggregate per-symbol signals into final scored output compatible with
SocialSignalPayload.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def aggregate(signals: list[dict[str, Any]], symbols: list[str]) -> list[dict[str, Any]]:
    """Aggregate per-symbol signals into final scored output."""
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for s in signals:
        by_symbol[s["symbol"]].append(s)

    results: list[dict[str, Any]] = []
    for sym in symbols:
        sym_signals = by_symbol.get(sym.upper(), [])
        if not sym_signals:
            continue

        sentiments = [s.get("sentiment", 0) for s in sym_signals]
        avg_sentiment = sum(sentiments) / len(sentiments)

        # Score: map -1..1 sentiment to 0..1
        score = (avg_sentiment + 1) / 2

        # Direction
        if avg_sentiment > 0.1:
            direction = "bullish"
        elif avg_sentiment < -0.1:
            direction = "bearish"
        else:
            direction = "neutral"

        # Contrarian: extreme one-way = reversal signal
        contrarian = abs(avg_sentiment) > 0.85

        # Echo chamber: any signal flagged?
        echo = any(s.get("echo_chamber", False) for s in sym_signals)

        results.append(
            {
                "symbol": sym.upper(),
                "score": round(score, 3),
                "direction": direction,
                "source_count": len(sym_signals),
                "contrarian_flag": contrarian,
                "echo_chamber_flag": echo,
            }
        )

    return results
