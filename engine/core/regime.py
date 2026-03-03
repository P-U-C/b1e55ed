"""engine.core.regime — regime metadata available to all layers."""

from __future__ import annotations

# Confidence cap per regime (0-10 scale, converted to 0.0-1.0 at point of use).
# These are the canonical regime caps. engine.brain.conviction imports from here.
REGIME_CAPS: dict[str, float] = {
    "BULL": 10.0,
    "BEAR": 7.0,
    "TRANSITION": 6.0,
    "CRISIS": 4.0,
}
