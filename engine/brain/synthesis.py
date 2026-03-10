"""engine.brain.synthesis

Six domains. One truth.
The synthesis is the conversation between them.

This module ports the *v2* synthesis philosophy from the legacy system:
- feature vectors per domain are preserved (no v1 score-only fallback)
- domain weights are applied explicitly (config presets)
- missing/stale domains degrade gracefully via data quality

"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from typing import Any, Final

from engine.brain.hierarchy import HierarchyEngine, HierarchyResult
from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType
from engine.core.types import CANONICAL_DOMAINS, FeatureSnapshot


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _mean(xs: list[float]) -> float | None:
    if not xs:
        return None
    return float(sum(xs) / len(xs))


_DEFAULT_DECAY_LAMBDA = 0.01  # half-life ~70 minutes
# Shannon: information is the resolution of uncertainty. At lambda=0.01, resolving power halves every 70 minutes.


# Ebbinghaus charted the forgetting curve in 1885: R = exp(-t/S). He used nonsense syllables.
# Memory, radioactive isotope, market signal -- the mathematics of decay is invariant across domains.
def _freshness_factor(event_ts: datetime, now: datetime, lambda_: float = _DEFAULT_DECAY_LAMBDA) -> float:
    """Exponential freshness decay: exp(-λ × age_minutes). Clamped to [0.01, 1.0]."""
    if event_ts.tzinfo is None:
        event_ts = event_ts.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    age_minutes = max(0.0, (now - event_ts).total_seconds() / 60.0)
    factor = math.exp(-lambda_ * age_minutes)
    return max(0.01, min(1.0, factor))


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    """Output of v2 synthesis for a symbol."""

    snapshot: FeatureSnapshot
    domain_scores: dict[str, float]  # 0..1 per domain (only domains with features)
    weights_used: dict[str, float]  # domain -> weight used this cycle (after quality adjustment)
    weighted_score: float  # 0..1 (domain_scores ⋅ weights_used)
    hierarchy_factors: dict[str, float] = field(default_factory=dict)  # domain -> final hierarchy multiplier
    regime_tag: str = "unknown"  # per-asset regime (populated by synthesize_with_regime)


class FeatureExtractor:
    """Extract feature vectors from events.

    In v2, the feature vector is the input contract.
    """

    DOMAIN_BY_EVENT_TYPE: Final[dict[EventType, str]] = {
        EventType.SIGNAL_CURATOR_V1: "curator",
        EventType.SIGNAL_ONCHAIN_V1: "onchain",
        EventType.SIGNAL_STABLECOIN_V1: "onchain",
        EventType.SIGNAL_WHALE_V1: "onchain",
        EventType.SIGNAL_TRADFI_V1: "tradfi",
        EventType.SIGNAL_ETF_V1: "tradfi",
        EventType.SIGNAL_SOCIAL_V1: "social",
        EventType.SIGNAL_SENTIMENT_V1: "social",
        EventType.SIGNAL_ACI_V1: "social",
        EventType.SIGNAL_TA_V1: "technical",
        EventType.SIGNAL_ORDERBOOK_V1: "technical",
        EventType.SIGNAL_EVENTS_V1: "events",
    }

    def extract_domain_features(self, *, event_type: EventType, payload: dict[str, Any]) -> dict[str, float]:
        """Map a typed payload into a compact feature vector."""

        p = payload

        if event_type == EventType.SIGNAL_TA_V1:
            out: dict[str, float] = {}
            if p.get("rsi_14") is not None:
                out["rsi_14"] = float(p["rsi_14"])
            for k in ["ema_20", "ema_50", "ema_200", "bb_position", "volume_ratio", "trend_strength", "support_distance", "resistance_distance"]:
                if p.get(k) is not None:
                    out[k] = float(p[k])
            return out

        if event_type == EventType.SIGNAL_ONCHAIN_V1:
            out = {}
            for k in ["whale_netflow", "exchange_flow", "active_addresses_change", "price_momentum_24h"]:
                if p.get(k) is not None:
                    out[k] = float(p[k])
            return out

        if event_type == EventType.SIGNAL_TRADFI_V1:
            out = {}
            for k in ["basis_annualized", "funding_annualized", "oi_change_pct", "meltup_score"]:
                if p.get(k) is not None:
                    out[k] = float(p[k])
            return out

        if event_type == EventType.SIGNAL_SOCIAL_V1:
            out = {"score": float(p.get("score", 0.0))}
            out["source_count"] = float(p.get("source_count", 0))
            out["contrarian_flag"] = 1.0 if p.get("contrarian_flag") else 0.0
            out["echo_chamber_flag"] = 1.0 if p.get("echo_chamber_flag") else 0.0
            return out

        if event_type == EventType.SIGNAL_SENTIMENT_V1:
            out = {}
            if p.get("fear_greed") is not None:
                out["fear_greed"] = float(p["fear_greed"])
            if p.get("fear_greed_change_7d") is not None:
                out["fear_greed_change_7d"] = float(p["fear_greed_change_7d"])
            return out

        if event_type == EventType.SIGNAL_EVENTS_V1:
            out = {}
            if p.get("headline_sentiment") is not None:
                out["headline_sentiment"] = float(p["headline_sentiment"])
            if p.get("impact_score") is not None:
                out["impact_score"] = float(p["impact_score"])
            out["event_count"] = float(p.get("event_count", 0))
            return out

        if event_type == EventType.SIGNAL_CURATOR_V1:
            # Curator conviction is 0..10 (by contract)
            out = {"conviction": float(p.get("conviction", 0.0))}
            # Direction is categorical; model it as signed direction feature.
            d = str(p.get("direction", "neutral")).lower()
            out["direction"] = {"bullish": 1.0, "bearish": -1.0, "neutral": 0.0}.get(d, 0.0)
            return out

        if event_type == EventType.SIGNAL_ACI_V1:
            # Consensus score is -10..+10
            return {
                "consensus_score": float(p.get("consensus_score", 0.0)),
                "dispersion": float(p.get("dispersion", 0.0)),
            }

        if event_type == EventType.SIGNAL_ETF_V1:
            out = {}
            if p.get("daily_flow_usd") is not None:
                out["daily_flow_usd"] = float(p["daily_flow_usd"])
            out["streak_days"] = float(p.get("streak_days", 0))
            if p.get("cumulative_7d") is not None:
                out["cumulative_7d"] = float(p["cumulative_7d"])
            return out

        if event_type == EventType.SIGNAL_WHALE_V1:
            out = {}
            if p.get("smart_money_netflow") is not None:
                out["smart_money_netflow"] = float(p["smart_money_netflow"])
            if p.get("top_holders_change") is not None:
                out["top_holders_change"] = float(p["top_holders_change"])
            return out

        if event_type == EventType.SIGNAL_STABLECOIN_V1:
            out = {}
            if p.get("supply_change_24h") is not None:
                out["supply_change_24h"] = float(p["supply_change_24h"])
            if p.get("supply_change_7d") is not None:
                out["supply_change_7d"] = float(p["supply_change_7d"])
            out["mint_burn_events"] = float(p.get("mint_burn_events", 0))
            return out

        # Unknown: no features
        return {}


class VectorSynthesis:
    """v2 synthesis engine: builds feature snapshots + computes a weighted score."""

    DOMAINS: Final[list[str]] = sorted(CANONICAL_DOMAINS)

    def __init__(self, config: Config, db: Database):
        self.config = config
        self.db = db
        self.extractor = FeatureExtractor()

    def build_snapshot(
        self,
        *,
        cycle_id: str,
        symbol: str,
        as_of: datetime | None = None,
        lookback_limit: int = 200,
    ) -> FeatureSnapshot:
        now = as_of or datetime.now(tz=UTC)

        feats: dict[str, dict[str, float]] = {d: {} for d in self.DOMAINS}
        source_event_ids: list[str] = []

        # We use latest per event type for simplicity and determinism.
        for et, dom in self.extractor.DOMAIN_BY_EVENT_TYPE.items():
            evs = self.db.get_events(event_type=et, limit=lookback_limit)
            # pick latest for symbol (if payload has symbol)
            chosen = None
            for ev in evs:
                p = ev.payload
                sym = p.get("symbol")
                if sym is None and et == EventType.SIGNAL_STABLECOIN_V1:
                    # stablecoin events are not per symbol; ignore here
                    continue
                if sym is not None and str(sym).upper() != str(symbol).upper():
                    continue
                chosen = ev
                break
            if chosen is None:
                continue

            vec = self.extractor.extract_domain_features(event_type=et, payload=chosen.payload)
            if not vec:
                continue

            factor = _freshness_factor(chosen.ts, now)
            decayed_vec = {k: float(v) * factor for k, v in vec.items()}

            feats[dom].update(decayed_vec)
            source_event_ids.append(chosen.id)

        # Drop empty domains to keep snapshot compact.
        feats = {d: v for (d, v) in feats.items() if v}

        return FeatureSnapshot(
            cycle_id=cycle_id,
            symbol=str(symbol).upper(),
            ts=now,
            features=feats,
            source_event_ids=sorted(set(source_event_ids)),
            regime=None,
            version="v2",
        )

    def domain_score(
        self,
        domain: str,
        features: dict[str, float],
        *,
        symbol: str | None = None,
    ) -> float | None:
        """Compute a 0..1 domain score from raw feature values.

        ``symbol`` is used by the on-chain path to scale flows relative to the
        asset's market cap / volume (via :mod:`engine.brain.signal_normalizer`).
        Other domains ignore it.  Omitting it falls back to default thresholds.

        This is intentionally simple; v2 keeps vectors for later learning.
        """
        from engine.brain.signal_normalizer import normalize_onchain_signal  # noqa: I001

        dom = str(domain)
        f = features
        scores: list[float] = []

        if dom == "technical":
            rsi = f.get("rsi_14")
            if rsi is not None:
                scores.append(_clamp01((70.0 - float(rsi)) / 40.0))  # 30->1, 70->0
            ts = f.get("trend_strength")
            if ts is not None:
                scores.append(_clamp01(float(ts)))
            vr = f.get("volume_ratio")
            if vr is not None:
                scores.append(_clamp01((float(vr) - 0.5) / 2.0))

        elif dom == "onchain":
            # Use asset-aware normalizer — falls back to BTC/ETH/SOL defaults when
            # symbol is None or not in the thresholds table.
            sym = symbol or ""
            ns = normalize_onchain_signal(sym, dict(f))
            if ns.whale_netflow is not None:
                scores.append(ns.whale_netflow)
            if ns.exchange_flow is not None:
                scores.append(ns.exchange_flow)
            if ns.price_momentum_24h is not None:
                scores.append(ns.price_momentum_24h)

        elif dom == "tradfi":
            fund = f.get("funding_annualized")
            if fund is not None:
                # Parameterized via scoring_params (P2.4). Shadow-safe defaults.
                try:
                    from engine.brain.scoring import get_param as _gp

                    _fc = _gp(self.db, "tradfi.funding_optimal_center")
                    _fs = _gp(self.db, "tradfi.funding_scale")
                except Exception:
                    _fc, _fs = 10.0, 30.0
                scores.append(_clamp01(1.0 - abs(float(fund) - _fc) / _fs))
            basis = f.get("basis_annualized")
            if basis is not None:
                try:
                    from engine.brain.scoring import get_param as _gp2

                    _bc = _gp2(self.db, "tradfi.basis_optimal_center")
                    _bs = _gp2(self.db, "tradfi.basis_scale")
                except Exception:
                    _bc, _bs = 5.0, 8.0
                scores.append(_clamp01(1.0 - abs(float(basis) - _bc) / _bs))
            oi = f.get("oi_change_pct")
            if oi is not None:
                scores.append(_clamp01(0.5 + float(oi) / 40.0))

        elif dom == "social":
            if "score" in f:
                scores.append(_clamp01((float(f["score"]) + 10.0) / 20.0))
            if "fear_greed" in f:
                # low fear/greed is contrarian bullish
                scores.append(_clamp01((50.0 - float(f["fear_greed"])) / 50.0))

        elif dom == "events":
            hs = f.get("headline_sentiment")
            if hs is not None:
                scores.append(_clamp01((float(hs) + 1.0) / 2.0))
            impact = f.get("impact_score")
            if impact is not None:
                scores.append(_clamp01(float(impact)))

        elif dom == "curator":
            conv = f.get("conviction")
            if conv is not None:
                scores.append(_clamp01(float(conv) / 10.0))
            d = f.get("direction")
            if d is not None:
                # treat bullish direction as a slight boost
                scores.append(_clamp01(0.5 + 0.25 * float(d)))

        return _mean(scores)

    def _load_karma_multipliers(self) -> dict[str, float]:
        """Load average karma_score per domain from producer_karma table.

        Returns a dict of domain -> average karma_score for producers in that domain.
        If table is empty or doesn't exist, returns empty dict (Phase 0 neutral).
        """
        try:
            # producer_karma has producer_id (which maps to source/producer_id in SIGNAL_ACCEPTED_V1)
            # We need to map producer_id -> domain. Query the latest SIGNAL_ACCEPTED_V1 events
            # to build producer -> domain mapping, then average karma per domain.
            rows = self.db.fetchall("SELECT producer_id, karma_score FROM producer_karma")
            if not rows:
                return {}

            producer_domains = self._build_producer_domain_map()
            if not producer_domains:
                return {}

            # Average karma per domain
            domain_scores: dict[str, list[float]] = {}
            for row in rows:
                pid = str(row[0])
                ks = float(row[1])
                dom = producer_domains.get(pid)
                if dom:
                    domain_scores.setdefault(dom, []).append(ks)

            if not domain_scores:
                return {}

            return {dom: sum(scores) / len(scores) for dom, scores in domain_scores.items()}
        except Exception:
            return {}

    def _build_producer_domain_map(self) -> dict[str, str]:
        """Build producer_name -> domain map from recent SIGNAL_ACCEPTED_V1 events."""
        import json as _json

        try:
            rows = self.db.fetchall(
                "SELECT payload FROM events WHERE type = ? ORDER BY ts DESC LIMIT 500",
                (str(EventType.SIGNAL_ACCEPTED_V1),),
            )
            mapping: dict[str, str] = {}
            for row in rows:
                payload = _json.loads(row[0]) if isinstance(row[0], str) else row[0]
                producer_id = str(payload.get("producer_id", "")).strip()
                domain = str(payload.get("domain", "")).strip().lower()
                if producer_id and domain and producer_id not in mapping:
                    mapping[producer_id] = domain
            return mapping
        except Exception:
            return {}

    def synthesize(
        self,
        *,
        cycle_id: str,
        symbol: str,
        weights: dict[str, float] | None = None,
        as_of: datetime | None = None,
        quality_adjustment: dict[str, float] | None = None,
    ) -> SynthesisResult:
        snapshot = self.build_snapshot(cycle_id=cycle_id, symbol=symbol, as_of=as_of)
        hier_result: HierarchyResult | None = None

        base_weights = weights or self.config.weights.model_dump()
        # quality_adjustment: domain -> 0..1 multiplier (already computed by DataQualityMonitor)
        if quality_adjustment:
            adjusted = {d: float(base_weights.get(d, 0.0)) * _clamp01(float(quality_adjustment.get(d, 1.0))) for d in base_weights}
            total = sum(adjusted.values())
            weights_used = {k: (v / total if total > 0 else 0.0) for k, v in adjusted.items()}
        else:
            weights_used = dict(base_weights)

        # Flywheel: apply producer karma as weight multiplier
        karma_multipliers = self._load_karma_multipliers()
        if karma_multipliers:
            for dom in list(weights_used.keys()):
                mult = karma_multipliers.get(dom, 1.0)
                weights_used[dom] = float(weights_used[dom]) * float(mult)
            # Re-normalize
            total_w = sum(weights_used.values())
            if total_w > 0:
                weights_used = {k: v / total_w for k, v in weights_used.items()}

        # P4.1: Hierarchical weighting — best-effort modulation of domain priors.
        try:
            producer_domain_map = self._build_producer_domain_map()
            if producer_domain_map:
                hierarchy = HierarchyEngine(self.db)
                regime_tag = getattr(snapshot, "regime", None) or "unknown"
                hier_result = hierarchy.compute(
                    symbol=symbol,
                    regime=str(regime_tag),
                    producer_domain_map=producer_domain_map,
                )
                for dom in list(weights_used.keys()):
                    mult = hier_result.multipliers.get(dom, 1.0)
                    weights_used[dom] = float(weights_used[dom]) * float(mult)
                # Re-normalize
                total_w = sum(weights_used.values())
                if total_w > 0:
                    weights_used = {k: v / total_w for k, v in weights_used.items()}
        except Exception:
            pass  # hierarchy is best-effort; never break synthesis

        domain_scores: dict[str, float] = {}
        for dom, feats in snapshot.features.items():
            s = self.domain_score(dom, feats)
            if s is not None:
                domain_scores[dom] = float(s)

        weighted_score = 0.0
        for dom, s in domain_scores.items():
            weighted_score += float(weights_used.get(dom, 0.0)) * float(s)

        return SynthesisResult(
            snapshot=snapshot,
            domain_scores=domain_scores,
            weights_used=weights_used,
            weighted_score=_clamp01(weighted_score),
            hierarchy_factors=(dict(hier_result.multipliers) if hier_result is not None else {}),
        )

    def synthesize_with_regime(
        self,
        *,
        cycle_id: str,
        symbol: str,
        quality_adjustment: dict[str, float] | None,
        regime_detector: Any,
        as_of: datetime | None = None,
        weights: dict[str, float] | None = None,
    ) -> SynthesisResult:
        """Run synthesis and attach a per-asset regime tag.

        Existing callers can continue using ``synthesize()``; this method is an
        additive convenience for pipelines that need symbol-local regime tags.
        """
        result = self.synthesize(
            cycle_id=cycle_id,
            symbol=symbol,
            as_of=as_of,
            weights=weights,
            quality_adjustment=quality_adjustment,
        )
        regime_result = regime_detector.detect_for_asset(result.snapshot)

        return SynthesisResult(
            snapshot=result.snapshot,
            domain_scores=result.domain_scores,
            weights_used=result.weights_used,
            weighted_score=result.weighted_score,
            hierarchy_factors=result.hierarchy_factors,
            regime_tag=regime_result.state.regime,
        )
