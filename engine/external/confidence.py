"""Confidence normalization strategies for external adapter observations.

All strategies map raw producer confidence values into the Brier-scoring
range [0.55, 0.99] used by the b1e55ed calibration system.
"""

from __future__ import annotations

_MIN_CONF = 0.55
_MAX_CONF = 0.99


def normalize_confidence(
    value: float | None,
    strategy: str = "direct",
    *,
    hit_rate: float | None = None,
) -> float:
    """Normalize confidence to [0.55, 0.99] for Brier scoring.

    Args:
        value: Raw confidence from the external source (0.0–1.0).
        strategy: Normalization strategy.
            - ``"direct"`` — clamp value to [0.55, 0.99].
            - ``"hit_rate"`` — use *hit_rate* (or *value*) as a proxy;
              applies the same clamp.
            - ``"logistic"`` — apply a mild logistic squash centered at 0.75
              before clamping, compressing extremes.
        hit_rate: Optional historical hit-rate metric from the external source.
            Only used when strategy is ``"hit_rate"``.

    Returns:
        Normalized confidence in [0.55, 0.99].
    """
    if strategy == "direct":
        if value is None:
            return _MIN_CONF
        return _clamp(float(value))

    elif strategy == "hit_rate":
        proxy = hit_rate if hit_rate is not None else value
        if proxy is None:
            return _MIN_CONF
        return _clamp(float(proxy))

    elif strategy == "logistic":
        if value is None:
            return _MIN_CONF
        import math

        # Mild logistic centred at 0.5 — keeps signal direction, compresses extremes.
        x = float(value)
        squashed = 1.0 / (1.0 + math.exp(-10 * (x - 0.5)))
        return _clamp(squashed)

    # Unknown strategy — return floor.
    return _MIN_CONF


def _clamp(v: float) -> float:
    """Clamp value into [_MIN_CONF, _MAX_CONF]."""
    return max(_MIN_CONF, min(_MAX_CONF, v))
