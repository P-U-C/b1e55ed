"""engine.brain.regime

Deterministic market regime detection.

This module ports the *spirit* of the legacy regime detector, but conforms to
SDD/PRD v3 requirements:
- primary regimes: BULL, BEAR, CRISIS, TRANSITION
- evidence comes from synthesis feature vectors when available
- emit REGIME_CHANGE_V1 events only on change

"Soros: the observer is part of the system." (see Easter Egg reference)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    UTC = UTC  # noqa: N806

from typing import Any

from engine.core.database import Database
from engine.core.events import EventType
from engine.core.types import FeatureSnapshot, RegimeState


@dataclass(frozen=True, slots=True)
class RegimeResult:
    state: RegimeState
    changed: bool
    previous: str | None


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class RegimeDetector:
    def __init__(self, db: Database):
        self.db = db
        self._last_regime: str | None = None

    def detect(self, *, as_of: datetime | None = None, btc_snapshot: FeatureSnapshot | None = None) -> RegimeResult:
        now = as_of or datetime.now(tz=UTC)

        features: dict[str, float] = {}
        if btc_snapshot is not None:
            # Pull a few canonical indicators from available domains
            tech = btc_snapshot.features.get("technical", {})
            tradfi = btc_snapshot.features.get("tradfi", {})
            sent = btc_snapshot.features.get("social", {})

            rsi = _to_float(tech.get("rsi_14"))
            if rsi is not None:
                features["btc_rsi"] = rsi

            funding = _to_float(tradfi.get("funding_annualized"))
            if funding is not None:
                features["funding_annualized"] = funding

            basis = _to_float(tradfi.get("basis_annualized"))
            if basis is not None:
                features["basis_annualized"] = basis

            fng = _to_float(sent.get("fear_greed"))
            if fng is not None:
                features["fear_greed"] = fng

        # Rule counts (best-effort, missing data just reduces confidence)
        bull = 0
        bear = 0
        crisis = 0

        funding = features.get("funding_annualized")
        basis = features.get("basis_annualized")
        rsi = features.get("btc_rsi")
        fng = features.get("fear_greed")

        if funding is not None and 5.0 < funding < 30.0:
            bull += 1
        if basis is not None and 3.0 < basis < 8.0:
            bull += 1
        if rsi is not None and rsi > 50.0:
            bull += 1
        if fng is not None and fng > 40.0:
            bull += 1

        if funding is not None and funding < 0.0:
            bear += 1
        if basis is not None and basis < 2.0:
            bear += 1
        if rsi is not None and rsi < 30.0:
            bear += 1
        if fng is not None and fng < 25.0:
            bear += 1

        if funding is not None and funding < -10.0:
            crisis += 1
        if basis is not None and (basis > 8.0 or basis < 1.0):
            crisis += 1
        if fng is not None and fng < 15.0:
            crisis += 1

        if crisis >= 2:
            regime = "CRISIS"
        elif bull >= 3:
            regime = "BULL"
        elif bear >= 3:
            regime = "BEAR"
        else:
            regime = "TRANSITION"

        evidence = {k: float(v) for k, v in features.items()}
        state = RegimeState(regime=regime, ts=now, evidence=evidence)

        prev = self._last_regime
        changed = prev is not None and prev != regime
        self._last_regime = regime

        return RegimeResult(state=state, changed=changed, previous=prev)

    # Ashby's Law of Requisite Variety: a controller needs at least as much variety as the system it controls.
    # One global regime for n assets has less variety than the market. Per-asset is the correct resolution.
    def detect_for_asset(self, snapshot: FeatureSnapshot) -> RegimeResult:
        """Compute regime for a single asset using its own feature snapshot.

        Uses asset-specific technical/tradfi features and falls back to the
        last known global regime when no usable indicators are present.
        """
        now = snapshot.ts

        tech = snapshot.features.get("technical", {})
        tradfi = snapshot.features.get("tradfi", {})
        social = snapshot.features.get("social", {})

        rsi = _to_float(tech.get("rsi_14"))
        ema_20 = _to_float(tech.get("ema_20"))
        ema_50 = _to_float(tech.get("ema_50"))
        ema_200 = _to_float(tech.get("ema_200"))

        funding = _to_float(tradfi.get("funding_annualized"))
        basis = _to_float(tradfi.get("basis_annualized"))
        fear_greed = _to_float(social.get("fear_greed"))

        evidence: dict[str, float] = {}
        if rsi is not None:
            evidence["rsi_14"] = rsi
        if ema_20 is not None:
            evidence["ema_20"] = ema_20
        if ema_50 is not None:
            evidence["ema_50"] = ema_50
        if ema_200 is not None:
            evidence["ema_200"] = ema_200
        if funding is not None:
            evidence["funding_annualized"] = funding
        if basis is not None:
            evidence["basis_annualized"] = basis
        if fear_greed is not None:
            evidence["fear_greed"] = fear_greed

        prev = self._last_regime

        # Von Foerster: the observer is part of the system. An asset's regime is local. The global frame is an approximation.
        # No usable indicators: carry forward last known global regime, else
        # default to TRANSITION for deterministic behavior.
        if not evidence:
            regime = prev or "TRANSITION"
            state = RegimeState(regime=regime, ts=now, evidence=evidence)
            changed = prev is not None and prev != regime
            return RegimeResult(state=state, changed=changed, previous=prev)

        bull = 0
        bear = 0

        # Crisis should trigger on extreme stress from any key indicator.
        crisis = (funding is not None and funding < -0.05) or (rsi is not None and rsi < 20.0)

        # Bullish evidence: positive momentum + healthy basis/funding/EMA trend.
        if rsi is not None and rsi > 55.0:
            bull += 1
        if basis is not None and basis > 3.0:
            bull += 1
        if funding is not None and funding > 0.0:
            bull += 1
        if ema_20 is not None and ema_50 is not None and ema_20 > ema_50:
            bull += 1
        if ema_50 is not None and ema_200 is not None and ema_50 > ema_200:
            bull += 1

        # Bearish evidence: weak momentum + negative funding/structure.
        if rsi is not None and rsi < 45.0:
            bear += 1
        if funding is not None and funding < 0.0:
            bear += 1
        if basis is not None and basis < 2.0:
            bear += 1
        if ema_20 is not None and ema_50 is not None and ema_20 < ema_50:
            bear += 1
        if ema_50 is not None and ema_200 is not None and ema_50 < ema_200:
            bear += 1
        if fear_greed is not None and fear_greed < 25.0:
            bear += 1

        if crisis:
            regime = "CRISIS"
        elif bull >= 2 and bull > bear:
            regime = "BULL"
        elif bear >= 2 and bear >= bull:
            regime = "BEAR"
        else:
            regime = "TRANSITION"

        state = RegimeState(regime=regime, ts=now, evidence=evidence)
        changed = prev is not None and prev != regime

        return RegimeResult(state=state, changed=changed, previous=prev)

    def emit_if_changed(self, result: RegimeResult, *, source: str = "brain.regime") -> None:
        if not result.changed:
            return

        payload = {
            "regime": result.state.regime,
            "previous": result.previous,
            "evidence": result.state.evidence,
        }
        self.db.append_event(event_type=EventType.REGIME_CHANGE_V1, payload=payload, source=source)
