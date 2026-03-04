"""engine.core.forecast

Helpers for creating and validating FORECAST_V1 events.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from engine.core.events import AbstentionReason, ForecastLifecycleState, ForecastPayload


def make_forecast_id() -> str:
    return str(uuid.uuid4())


def compute_reasoning_hash(candidate: dict[str, Any], critique: str = "", rationale: str = "") -> str:
    """sha256 of the full reasoning bundle."""
    bundle = json.dumps({"candidate": candidate, "critique": critique, "rationale": rationale}, sort_keys=True)
    return hashlib.sha256(bundle.encode()).hexdigest()


def abstain(
    *,
    source: str,
    asset: str,
    horizon: str,
    reason: AbstentionReason,
    regime_tag: str = "unknown",
    visible_signal_refs: list[str] | None = None,
) -> ForecastPayload:
    """Convenience constructor for a no_forecast abstention."""
    return ForecastPayload(
        forecast_id=make_forecast_id(),
        asset=asset,
        horizon=horizon,
        action="no_forecast",
        confidence=0.0,
        source=source,
        regime_tag=regime_tag,
        lifecycle_state=ForecastLifecycleState.NEW,
        abstention_reason=reason,
        visible_signal_refs=visible_signal_refs or [],
        used_signal_refs=[],
    )
