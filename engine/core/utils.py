"""engine.core.utils

Shared low-level utilities for the core layer.
Keep this module import-free of other engine.* modules to avoid circular deps.
"""

from __future__ import annotations


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp *value* into the closed interval [lo, hi]."""
    return max(lo, min(hi, float(value)))
