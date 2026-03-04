"""engine.core.self_memory

Producer self-memory confidence adjustment based on resolved forecast history.

This module provides a small, bounded confidence modulation layer that can be
applied before emitting a forecast. It does not change action (long/short/flat)
and is guarded against unstable feedback loops.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.core.utils import clamp

# Guardrail defaults
MIN_RESOLVED = 5
MAX_DELTA = 0.30
STREAK_WINDOW_DAYS = 3
LONG_WINDOW_DAYS = 90
STREAK_WEIGHT = 0.35

GOOD_BRIER_THRESHOLD = 0.20
POOR_BRIER_THRESHOLD = 0.33


@dataclass(slots=True)
class SelfMemoryResult:
    """Outcome of a self-memory query."""

    confidence_delta: float
    applied: bool
    reason: str
    long_term_brier: float | None
    recent_brier: float | None
    resolved_count: int
    skip_reason: str | None = None


@dataclass(slots=True)
class SelfMemoryConfig:
    """Configuration for self-memory behavior."""

    enabled: bool = True
    min_resolved: int = MIN_RESOLVED
    max_delta: float = MAX_DELTA
    streak_window_days: int = STREAK_WINDOW_DAYS
    long_window_days: int = LONG_WINDOW_DAYS
    streak_weight: float = STREAK_WEIGHT


# A grimoire is memory with teeth: lessons persist because they are callable.
class SelfMemory:
    """Compute confidence deltas from producer calibration history.

    - long-term Brier is the anchor
    - recent Brier adds bounded recency
    - optional regime performance contributes a small adjustment
    - final delta is clamped to configured max_delta
    """

    def __init__(self, db: Any, config: SelfMemoryConfig | None = None) -> None:
        self.db = db
        self.config = config or SelfMemoryConfig()

    def query(self, producer_name: str, asset: str, regime: str = "unknown") -> SelfMemoryResult:
        """Return a bounded confidence delta for *producer_name*.

        Args:
            producer_name: Producer ID used in calibration rows.
            asset: Included for call-site parity/future extension.
            regime: Current regime tag for optional regime-conditioned scoring.
        """
        _ = asset  # reserved for future asset-specific calibration windows
        cfg = self.config

        if not cfg.enabled:
            return SelfMemoryResult(
                confidence_delta=0.0,
                applied=False,
                reason="disabled",
                long_term_brier=None,
                recent_brier=None,
                resolved_count=0,
                skip_reason="self-memory disabled in config",
            )

        from engine.brain.calibration import brier_summary

        long_summary = brier_summary(self.db, producer_name, window_days=cfg.long_window_days)
        resolved = int(long_summary.get("count", 0) or 0)
        if resolved < cfg.min_resolved:
            return SelfMemoryResult(
                confidence_delta=0.0,
                applied=False,
                reason="insufficient_data",
                long_term_brier=None,
                recent_brier=None,
                resolved_count=resolved,
                skip_reason=f"only {resolved} resolved forecasts (need {cfg.min_resolved})",
            )

        long_raw = long_summary.get("mean_brier")
        long_brier = float(long_raw) if long_raw is not None else 0.25

        recent_summary = brier_summary(self.db, producer_name, window_days=cfg.streak_window_days)
        recent_count = int(recent_summary.get("count", 0) or 0)
        recent_brier: float | None
        if recent_count >= 2 and recent_summary.get("mean_brier") is not None:
            recent_brier = float(recent_summary["mean_brier"])
        else:
            recent_brier = None

        long_delta = _brier_to_delta(long_brier)
        recent_delta = _brier_to_delta(recent_brier) if recent_brier is not None else long_delta

        streak_weight = clamp(float(cfg.streak_weight), 0.0, 1.0)
        blended = (1.0 - streak_weight) * long_delta + streak_weight * recent_delta

        regime_stats = _regime_stats(long_summary.get("regime_breakdown"), regime)
        if regime_stats is not None:
            regime_brier = regime_stats.get("mean_brier")
            regime_count = int(regime_stats.get("count", 0) or 0)
            if regime_brier is not None and regime_count >= 3:
                regime_delta = _brier_to_delta(float(regime_brier))
                blended = (blended * 0.8) + (regime_delta * 0.2)

        final_delta = clamp(blended, -float(cfg.max_delta), float(cfg.max_delta))

        reason_parts = [f"long_brier={long_brier:.3f}"]
        if recent_brier is not None:
            reason_parts.append(f"recent_brier={recent_brier:.3f}")
        reason_parts.append(f"delta={final_delta:+.3f}")

        return SelfMemoryResult(
            confidence_delta=round(final_delta, 4),
            applied=True,
            reason=", ".join(reason_parts),
            long_term_brier=round(long_brier, 4),
            recent_brier=round(recent_brier, 4) if recent_brier is not None else None,
            resolved_count=resolved,
        )


def _regime_stats(regime_breakdown: Any, regime: str) -> dict[str, Any] | None:
    if not isinstance(regime_breakdown, dict):
        return None

    target = str(regime).upper()
    if target in regime_breakdown and isinstance(regime_breakdown[target], dict):
        return regime_breakdown[target]

    for key, value in regime_breakdown.items():
        if str(key).upper() == target and isinstance(value, dict):
            return value

    return None


def _brier_to_delta(brier: float) -> float:
    """Map Brier score to signed confidence delta."""
    if brier <= 0.10:
        return 0.15
    if brier <= GOOD_BRIER_THRESHOLD:
        return 0.08
    if brier <= 0.25:
        return 0.0
    if brier <= POOR_BRIER_THRESHOLD:
        return -0.10
    return -0.20
