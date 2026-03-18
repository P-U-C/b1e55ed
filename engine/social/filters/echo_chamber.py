"""engine.social.filters.echo_chamber

Flag symbols where sentiment is suspiciously uniform across sources.

When every source agrees strongly, it's either obviously true or coordinated
shilling. Either way, worth flagging.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def detect_echo_chamber(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag symbols where sentiment is suspiciously uniform across sources."""
    by_symbol: dict[str, list[float]] = defaultdict(list)

    for s in signals:
        by_symbol[s["symbol"]].append(s.get("sentiment", 0))

    for s in signals:
        sym_sentiments = by_symbol[s["symbol"]]
        if len(sym_sentiments) >= 3:
            avg = sum(sym_sentiments) / len(sym_sentiments)
            # If all sources agree strongly (>0.8 or <-0.8), flag echo chamber
            s["echo_chamber"] = abs(avg) > 0.8
        else:
            s["echo_chamber"] = False

    return signals
