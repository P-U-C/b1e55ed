"""Policy checks for external adapter observations.

Enforces quality gates — stale data, degraded health, low confidence —
before observations are emitted into the b1e55ed event stream.
"""

from __future__ import annotations

from engine.external.models import ExternalObservation


class AdapterPolicy:
    """Stateless policy gate for external observations.

    Args:
        min_confidence: Minimum acceptable confidence score (default 0.55).
        stale_threshold_sec: Maximum age in seconds before an observation
            is considered stale (used for explicit is_stale override; the
            producer's connector handles timestamp-based staleness).
    """

    def __init__(
        self,
        min_confidence: float = 0.55,
        stale_threshold_sec: int = 300,
    ) -> None:
        self.min_confidence = min_confidence
        self.stale_threshold_sec = stale_threshold_sec

    def should_skip(self, obs: ExternalObservation) -> tuple[bool, str]:
        """Evaluate whether an observation should be skipped.

        Checks are applied in priority order:
        1. HALT health state — hard stop, always skip.
        2. Stale flag — observation marked stale by the source.
        3. Low confidence — below configured threshold.

        Args:
            obs: The observation to evaluate.

        Returns:
            ``(skip, reason)`` where *skip* is True if the observation
            should be discarded, and *reason* is a short machine-readable
            string describing why.
        """
        if obs.health_state == "HALT":
            return True, "health_halt"

        if obs.is_stale:
            return True, "stale"

        if obs.confidence < self.min_confidence:
            return True, "low_confidence"

        return False, ""

    def is_degraded(self, obs: ExternalObservation) -> bool:
        """Return True if the source is degraded (but not halted)."""
        return obs.health_state == "DEGRADED"
