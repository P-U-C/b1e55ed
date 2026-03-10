"""engine.social.scoring.divergence

Cross-source divergence detection — passthrough for now.

Future: flag when social sentiment diverges from on-chain or price action.
"""

from __future__ import annotations

from typing import Any


def detect_divergence(aggregated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect divergence between social sentiment and other signals. Passthrough for now."""
    return aggregated
