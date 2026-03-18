"""engine.social.scoring.influencer

Influencer weighting — passthrough for now.

Future: weight signals by source credibility/influence scores.
"""

from __future__ import annotations

from typing import Any


def apply_influencer_weighting(aggregated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply influencer weighting to aggregated signals. Passthrough for now."""
    return aggregated
