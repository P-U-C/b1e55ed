"""engine.brain.conviction_v2_bridge

Helper that computes v2 regime + CTS values for a single symbol,
keeping the orchestrator free of v2-specific logic.

Called from the conviction-scoring loop in orchestrator.run_cycle().
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from engine.brain.cts_v2 import compute_cts
from engine.brain.regime_v2 import RegimeDetectorV2, RegimeV2Result

log = logging.getLogger("b1e55ed.conviction_v2_bridge")


@dataclass(frozen=True)
class V2Overrides:
    """Regime multiplier + CTS produced by the v2 path."""

    regime_multiplier: float
    cts: float
    regime_label: str


def compute_v2_overrides(
    regime_result: RegimeV2Result | None,
    snapshot_features: dict[str, Any],
    calibration: dict[str, Any] | None,
) -> V2Overrides | None:
    """Derive v2 regime multiplier, CTS, and label for one symbol.

    Returns *None* when the v2 path is unavailable (no regime result).
    """
    if regime_result is None:
        return None

    tradfi = snapshot_features.get("tradfi", {})
    tech = snapshot_features.get("technical", {})

    cts_features: dict[str, float | None] = {
        "rsi_14": tech.get("rsi_14"),
        "funding_annualized": tradfi.get("funding_annualized"),
        "basis_annualized": tradfi.get("basis_annualized"),
        "oi_change_pct": tradfi.get("oi_change_pct"),
    }

    cts_val = compute_cts(cts_features, calibration)

    return V2Overrides(
        regime_multiplier=regime_result.multiplier,
        cts=cts_val,
        regime_label=regime_result.label,
    )


def detect_regime_v2(
    detector: RegimeDetectorV2 | None,
    btc_snapshot: Any | None,
) -> RegimeV2Result | None:
    """Run the v2 regime detector, returning None on failure or if disabled."""
    if detector is None or btc_snapshot is None:
        return None
    try:
        return detector.detect_for_asset(btc_snapshot)
    except Exception:
        log.warning("regime_v2 failed, falling back to v1", exc_info=True)
        return None
