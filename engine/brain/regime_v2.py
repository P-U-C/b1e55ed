"""engine.brain.regime_v2

Continuous regime detector (v2).

Replaces the binary vote system with weighted, continuous scoring.
Funding rate is INVERTED: high positive funding = crowded longs = bearish.
RSI has a dead zone 40-60 (noise band).
Fear & Greed is a confirming signal only (low weight).

Spec: SPEC-regime-cts-redesign.md Section 3.1
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from engine.core.database import Database
from engine.core.events import EventType
from engine.core.types import FeatureSnapshot, RegimeState

from .regime import RegimeResult


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(x)))


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Feature normalizers: each returns [-1.0, 1.0]
# ---------------------------------------------------------------------------


def normalize_funding(rate: float) -> float:
    """Funding rate regime signal.

    INVERTED: high positive funding = crowded longs = slightly bearish context.
    Accepts annualized funding values (e.g. 6.21% annualized).
    Internally converts to per-period rate in percentage points:
      rate_pct = annualized / 365.0  (e.g. 6.21 -> 0.017%)
    Then applies tanh with 0.03 scaling (matching spec's small-number domain).
    """
    # Convert annualized percentage to per-period percentage
    # e.g. 3.65 annualized -> 0.01 per-period (matching spec's 0.01%)
    as_rate = rate / 365.0
    raw = -1.0 * math.tanh(as_rate / 0.03)  # inverted, scaled
    return _clamp(raw, -1.0, 1.0)


def normalize_basis(basis_annualized: float) -> float:
    """Annualized basis (futures premium).

    Positive basis = demand for leverage = bullish pressure.
    Center at 5% annualized (typical neutral).
    """
    centered = (basis_annualized - 5.0) / 10.0
    return _clamp(math.tanh(centered), -1.0, 1.0)


def normalize_rsi(rsi: float) -> float:
    """RSI with dead zone 40-60.

    Only meaningful at extremes. Linear ramp outside dead zone.
    """
    if 40 <= rsi <= 60:
        return 0.0
    elif rsi > 60:
        return min((rsi - 60) / 30.0, 1.0)  # 60->90 maps to 0->1
    else:
        return max((rsi - 40) / 30.0, -1.0)  # 40->10 maps to 0->-1


def normalize_fear_greed(fg: float) -> float:
    """Fear & Greed Index (0-100). Center at 50."""
    return _clamp((fg - 50) / 50.0, -1.0, 1.0)


# ---------------------------------------------------------------------------
# Weighted regime scoring
# ---------------------------------------------------------------------------

REGIME_WEIGHTS: dict[str, float] = {
    "funding_rate": 0.30,  # hardest signal, exchange-derived
    "basis": 0.30,  # arbitrage-derived, hard data
    "rsi": 0.15,  # lagging, only useful at extremes
    "fear_greed": 0.10,  # sentiment poll, confirming only
}
# Weights sum to 0.85 intentionally.
# Remaining 0.15 is reserved for OI_change when that producer is reliable.
# Until then, normalize by dividing by sum(weights).


def compute_regime_score(features: dict[str, float | None]) -> float:
    """Compute continuous regime score in [-1.0, 1.0].

    ``features`` keys: funding_rate, basis, rsi, fear_greed.
    Missing/None features are gracefully skipped.
    """
    normalizers = {
        "funding_rate": normalize_funding,
        "basis": normalize_basis,
        "rsi": normalize_rsi,
        "fear_greed": normalize_fear_greed,
    }

    total_weight = 0.0
    score = 0.0
    for feature, weight in REGIME_WEIGHTS.items():
        value = features.get(feature)
        if value is not None:
            normalized = normalizers[feature](value)
            score += normalized * weight
            total_weight += weight

    if total_weight == 0:
        return 0.0  # No data -> neutral

    return _clamp(score / total_weight, -1.0, 1.0)


def regime_multiplier(score: float) -> float:
    """Map regime score magnitude to confidence multiplier [0.65, 1.0].

    Uses a sqrt curve: fast gains from ambiguity, diminishing at extremes.
    """
    magnitude = abs(score)
    return 0.65 + (math.sqrt(magnitude) * 0.30)


def regime_label(score: float) -> str:
    """Backward-compatible categorical label from continuous score."""
    if score >= 0.5:
        return "BULL"
    elif score >= 0.2:
        return "LEAN_BULL"
    elif score > -0.2:
        return "NEUTRAL"
    elif score > -0.5:
        return "LEAN_BEAR"
    else:
        return "BEAR"


# ---------------------------------------------------------------------------
# V2 result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RegimeV2Result:
    """Output of the v2 continuous regime detector."""

    score: float  # [-1.0, 1.0]
    multiplier: float  # [0.65, 1.0]
    label: str  # BULL/LEAN_BULL/NEUTRAL/LEAN_BEAR/BEAR
    state: RegimeState
    changed: bool
    previous: str | None


# ---------------------------------------------------------------------------
# Detector class
# ---------------------------------------------------------------------------


class RegimeDetectorV2:
    """Continuous regime detector (v2).

    Replaces the binary vote system. Uses weighted feature normalization
    to produce a continuous score, continuous multiplier, and backward-compatible
    regime labels.
    """

    def __init__(self, db: Database):
        self.db = db
        self._last_label: str | None = None

    def _extract_features(self, snapshot: FeatureSnapshot) -> dict[str, float | None]:
        """Extract regime-relevant features from a snapshot."""
        tech = snapshot.features.get("technical", {})
        tradfi = snapshot.features.get("tradfi", {})
        social = snapshot.features.get("social", {})

        return {
            "funding_rate": _to_float(tradfi.get("funding_annualized")),
            "basis": _to_float(tradfi.get("basis_annualized")),
            "rsi": _to_float(tech.get("rsi_14")),
            "fear_greed": _to_float(social.get("fear_greed")),
        }

    def detect_for_asset(self, snapshot: FeatureSnapshot) -> RegimeV2Result:
        """Compute v2 regime for a single asset."""
        now = snapshot.ts
        features = self._extract_features(snapshot)

        score = compute_regime_score(features)
        mult = regime_multiplier(score)
        label = regime_label(score)

        evidence: dict[str, float] = {}
        for k, v in features.items():
            if v is not None:
                evidence[k] = float(v)
        evidence["regime_score_v2"] = score
        evidence["regime_multiplier_v2"] = mult

        state = RegimeState(regime=label, ts=now, evidence=evidence)

        prev = self._last_label
        changed = prev is not None and prev != label
        self._last_label = label

        result = RegimeV2Result(
            score=score,
            multiplier=mult,
            label=label,
            state=state,
            changed=changed,
            previous=prev,
        )

        # Emit FORECAST_V1 event documenting the calculation
        self._emit_forecast(result, features)

        return result

    def detect(
        self,
        *,
        as_of: datetime | None = None,
        btc_snapshot: FeatureSnapshot | None = None,
    ) -> RegimeResult:
        """Backward-compatible detect() that returns RegimeResult.

        Used by the orchestrator's global regime path.
        """
        now = as_of or datetime.now(tz=UTC)

        if btc_snapshot is not None:
            v2 = self.detect_for_asset(btc_snapshot)
            return RegimeResult(
                state=v2.state,
                changed=v2.changed,
                previous=v2.previous,
            )

        # No snapshot: neutral
        state = RegimeState(regime="NEUTRAL", ts=now, evidence={})
        prev = self._last_label
        changed = prev is not None and prev != "NEUTRAL"
        self._last_label = "NEUTRAL"
        return RegimeResult(state=state, changed=changed, previous=prev)

    def emit_if_changed(self, result: RegimeResult, *, source: str = "brain.regime_v2") -> None:
        """Emit REGIME_CHANGE_V1 event on label change."""
        if not result.changed:
            return
        payload = {
            "regime": result.state.regime,
            "previous": result.previous,
            "evidence": result.state.evidence,
        }
        self.db.append_event(event_type=EventType.REGIME_CHANGE_V1, payload=payload, source=source)

    def _emit_forecast(self, result: RegimeV2Result, features: dict[str, float | None]) -> None:
        """Log the regime calculation as a FORECAST_V1 event."""
        payload = {
            "type": "regime_v2",
            "score": result.score,
            "multiplier": result.multiplier,
            "label": result.label,
            "features": {k: v for k, v in features.items() if v is not None},
        }
        import contextlib

        with contextlib.suppress(Exception):
            self.db.append_event(
                event_type=EventType.FORECAST_V1,
                payload=payload,
                source="brain.regime_v2",
            )
