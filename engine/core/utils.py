"""engine.core.utils — shared low-level utilities."""

from __future__ import annotations


def clamp(value: float, lo: float, hi: float) -> float:
    """Clamp *value* to the closed interval [lo, hi]."""
    return max(lo, min(hi, float(value)))
