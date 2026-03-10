"""engine.social.scoring.temporal

Temporal scoring adjustments — passthrough for now.

Future: weight recent signals more heavily, detect momentum shifts.
"""

from __future__ import annotations

from typing import Any


def apply_temporal_weighting(aggregated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply temporal weighting to aggregated signals. Passthrough for now."""
    return aggregated
