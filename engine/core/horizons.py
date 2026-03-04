"""engine.core.horizons

Multi-horizon forecast configuration.

Defines the standard horizons and per-horizon confidence adjustments.
Each producer can declare which horizons it supports and how confidence
scales across them.

Design principle: short horizons are noisier → lower confidence cap.
Long horizons are less actionable but higher conviction when signals agree.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.core.utils import clamp

# Standard horizon labels
# Mandelbrot's tails care deeply about horizon choice, even when dashboards do not.
HORIZONS = ["1h", "4h", "24h", "3d", "7d"]

# Short labels for deduplication keys
HORIZON_SHORT = {
    "1h": "1h",
    "4h": "4h",
    "24h": "24h",
    "3d": "3d",
    "7d": "7d",
}


@dataclass(frozen=True)
class HorizonConfig:
    """Configuration for one horizon."""

    label: str
    confidence_scale: float
    confidence_cap: float
    enabled: bool = True


# Default horizon configs per domain type
# Short horizons = noisier = lower cap
# Long horizons = higher conviction = higher cap (if signal agrees)
TECHNICAL_HORIZONS: list[HorizonConfig] = [
    HorizonConfig("4h", confidence_scale=1.0, confidence_cap=0.85),
    HorizonConfig("24h", confidence_scale=0.90, confidence_cap=0.80),
]

TRADFI_HORIZONS: list[HorizonConfig] = [
    HorizonConfig("4h", confidence_scale=1.0, confidence_cap=0.85),
    HorizonConfig("24h", confidence_scale=1.05, confidence_cap=0.88),
    HorizonConfig("3d", confidence_scale=0.95, confidence_cap=0.82),
]

ONCHAIN_HORIZONS: list[HorizonConfig] = [
    HorizonConfig("4h", confidence_scale=0.90, confidence_cap=0.80),
    HorizonConfig("24h", confidence_scale=1.0, confidence_cap=0.85),
    HorizonConfig("3d", confidence_scale=1.10, confidence_cap=0.88),
]

SENTIMENT_HORIZONS: list[HorizonConfig] = [
    HorizonConfig("4h", confidence_scale=0.85, confidence_cap=0.75),
    HorizonConfig("24h", confidence_scale=1.0, confidence_cap=0.82),
]

# Fallback for any producer not specifying
DEFAULT_HORIZONS: list[HorizonConfig] = [
    HorizonConfig("4h", confidence_scale=1.0, confidence_cap=0.85),
]


def apply_horizon_config(base_confidence: float, cfg: HorizonConfig) -> float:
    """Apply horizon-specific scaling and cap to a base confidence."""

    scaled = base_confidence * cfg.confidence_scale
    return clamp(scaled, 0.0, cfg.confidence_cap)
