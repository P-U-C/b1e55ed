"""engine.brain.synthesis

Six domains. One truth.
The synthesis is the conversation between them.

This module ports the *v2* synthesis philosophy from the legacy system:
- feature vectors per domain are preserved (no v1 score-only fallback)
- domain weights are applied explicitly (config presets)
- missing/stale domains degrade gracefully via data quality

"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType
from engine.core.types import FeatureSnapshot


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _mean(xs: list[float]) -> float | None:
    if not xs:
        return None
    return float(sum(xs) / len(xs))


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    """Output of v2 synthesis for a symbol."""

    snapshot: FeatureSnapshot
    domain_scores: dict[str, float]  # 0..1 per domain (only domains with features)
    weights_used: dict[str, float]  # domain -> weight used this cycle (after quality adjustment)
    weighted_score: float  # 0..1 (domain_scores ⋅ weights_used)


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

    DOMAINS: Final[list[str]] = ["curator", "onchain", "tradfi", "social", "technical", "events"]

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
            feats[dom].update(vec)
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

    def domain_score(self, domain: str, features: dict[str, float]) -> float | None:
        """Compute a 0..1 domain score from raw feature values.

        This is intentionally simple; v2 keeps vectors for later learning.
        """

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
            whale = f.get("whale_netflow")
            if whale is not None:
                scores.append(_clamp01(0.5 + float(whale) / 200.0))
            exch = f.get("exchange_flow")
            if exch is not None:
                # positive exchange inflow bearish -> lower score
                scores.append(_clamp01(0.5 - float(exch) / 200.0))
            mom = f.get("price_momentum_24h")
            if mom is not None:
                scores.append(_clamp01(0.5 + float(mom) / 20.0))

        elif dom == "tradfi":
            fund = f.get("funding_annualized")
            if fund is not None:
                # ideal ~10, punish extremes
                scores.append(_clamp01(1.0 - abs(float(fund) - 10.0) / 30.0))
            basis = f.get("basis_annualized")
            if basis is not None:
                scores.append(_clamp01(1.0 - abs(float(basis) - 5.0) / 8.0))
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

        base_weights = weights or self.config.weights.model_dump()
        # quality_adjustment: domain -> 0..1 multiplier (already computed by DataQualityMonitor)
        if quality_adjustment:
            adjusted = {d: float(base_weights.get(d, 0.0)) * _clamp01(float(quality_adjustment.get(d, 1.0))) for d in base_weights}
            total = sum(adjusted.values())
            weights_used = {k: (v / total if total > 0 else 0.0) for k, v in adjusted.items()}
        else:
            weights_used = dict(base_weights)

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
        )
