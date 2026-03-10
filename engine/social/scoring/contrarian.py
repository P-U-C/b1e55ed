"""engine.social.scoring.contrarian

Adjust scores when contrarian conditions detected.

Extreme one-way sentiment often precedes reversals. Dampen confidence.
"""

from __future__ import annotations

from typing import Any


def apply_contrarian_signals(aggregated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Adjust scores when contrarian conditions detected."""
    for item in aggregated:
        if item.get("contrarian_flag"):
            # Contrarian = sentiment may reverse, adjust score toward neutral
            item["score"] = round(0.5 + (item["score"] - 0.5) * 0.3, 3)
    return aggregated
