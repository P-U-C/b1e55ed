"""engine.brain.cts_v2

Continuous CTS (Contrarian/Technical Score) v2.

Replaces the binary threshold system with sigmoid-based gradient scoring.
Each component contributes a smooth 0-1 score. No dependency on regime_score
(avoids circular dependency).

Calibration centers come from brain.db P75 percentiles via cts_calibration
config section.

Spec: SPEC-regime-cts-redesign.md Section 3.2
"""

from __future__ import annotations

import math
from typing import Any


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(x)))


def sigmoid(value: float, center: float, steepness: float = 1.0) -> float:
    """Smooth 0->1 score. 0.5 at center."""
    z = -steepness * (value - center)
    # Guard against overflow
    if z > 500:
        return 0.0
    if z < -500:
        return 1.0
    return 1.0 / (1.0 + math.exp(z))


# Default calibration (P75 from brain.db on blessed-patient-zero)
DEFAULT_CALIBRATION: dict[str, Any] = {
    "rsi_center": 60.16,
    "funding_center": 4.58,  # annualized, not rate
    "basis_center": 2.33,
    "oi_roc_center": 3.0,  # fallback: no data
}


def compute_cts(
    features: dict[str, float | None],
    calibration: dict[str, Any] | None = None,
) -> float:
    """Compute continuous CTS in [0.0, 35.0].

    ``features`` keys (all optional):
      - rsi_14: RSI value (0-100)
      - funding_annualized: annualized funding rate (e.g. 6.21)
      - basis_annualized: annualized basis (e.g. 3.0)
      - oi_change_pct: OI rate of change (e.g. 5.0)

    ``calibration`` keys (with defaults):
      - rsi_center: P75 RSI value (default 60.16)
      - funding_center: P75 |funding_annualized| (default 4.58)
      - basis_center: P75 |basis_annualized| (default 2.33)
      - oi_roc_center: P75 |oi_change_pct| (default 3.0)
    """
    cal = calibration or DEFAULT_CALIBRATION

    components: dict[str, float] = {}

    # RSI extremity (either direction is interesting for CTS)
    rsi = features.get("rsi_14")
    if rsi is not None:
        # Distance from 50 is what matters
        rsi_extremity = abs(float(rsi) - 50)
        rsi_center_raw = float(cal.get("rsi_center", 60.16))
        components["rsi_extreme"] = sigmoid(
            rsi_extremity,
            center=rsi_center_raw - 50,
            steepness=0.15,
        )

    # Funding rate magnitude (either direction = positioning pressure)
    # Data is annualized (e.g. 6.21), so steepness is tuned for that scale
    funding = features.get("funding_annualized")
    if funding is not None:
        funding_center = float(cal.get("funding_center", 4.58))
        components["funding_elevated"] = sigmoid(
            abs(float(funding)),
            center=funding_center,
            steepness=0.5,  # tuned for annualized scale (values 0-30)
        )

    # Basis magnitude
    basis = features.get("basis_annualized")
    if basis is not None:
        basis_center = float(cal.get("basis_center", 2.33))
        components["basis_elevated"] = sigmoid(
            abs(float(basis)),
            center=basis_center,
            steepness=0.3,
        )

    # OI rate of change (independent signal, no circular dependency)
    oi_roc = features.get("oi_change_pct")
    if oi_roc is not None:
        oi_center = float(cal.get("oi_roc_center", 3.0))
        components["oi_pressure"] = sigmoid(
            abs(float(oi_roc)),
            center=oi_center,
            steepness=0.5,
        )

    weights = {
        "rsi_extreme": 0.20,
        "funding_elevated": 0.30,
        "basis_elevated": 0.30,
        "oi_pressure": 0.20,
    }

    total_weight = 0.0
    raw = 0.0
    for key, weight in weights.items():
        if key in components:
            raw += components[key] * weight
            total_weight += weight

    if total_weight == 0:
        return 0.0

    normalized = raw / total_weight

    # Power curve to stretch lower range (where most trading happens)
    stretched = math.pow(normalized, 0.7)

    return _clamp(stretched * 35.0, 0.0, 35.0)
