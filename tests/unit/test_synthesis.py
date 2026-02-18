from __future__ import annotations

from datetime import UTC, datetime, timedelta

from engine.brain.synthesis import VectorSynthesis
from engine.core.database import Database
from engine.core.events import EventType


def test_synthesis_builds_6_domain_feature_vectors_and_applies_weights(test_config, temp_dir):
    db = Database(temp_dir / "brain.db")
    now = datetime.now(tz=UTC)

    # 6 domains: curator, onchain, tradfi, social, technical, events
    db.append_event(
        event_type=EventType.SIGNAL_CURATOR_V1,
        payload={"symbol": "BTC", "direction": "bullish", "conviction": 8.0, "rationale": ""},
        ts=now,
    )
    db.append_event(
        event_type=EventType.SIGNAL_ONCHAIN_V1,
        payload={"symbol": "BTC", "whale_netflow": 50.0, "exchange_flow": -10.0},
        ts=now,
    )
    db.append_event(
        event_type=EventType.SIGNAL_TRADFI_V1,
        payload={"symbol": "BTC", "funding_annualized": 10.0, "basis_annualized": 5.0},
        ts=now,
    )
    db.append_event(
        event_type=EventType.SIGNAL_SOCIAL_V1,
        payload={"symbol": "BTC", "score": 2.0, "direction": "bullish", "source_count": 10},
        ts=now,
    )
    db.append_event(
        event_type=EventType.SIGNAL_SENTIMENT_V1,
        payload={"symbol": "BTC", "fear_greed": 30.0},
        ts=now,
    )
    db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "BTC", "rsi_14": 35.0, "trend_strength": 0.7},
        ts=now,
    )
    db.append_event(
        event_type=EventType.SIGNAL_EVENTS_V1,
        payload={"symbol": "BTC", "headline_sentiment": 0.2, "impact_score": 0.6, "event_count": 1},
        ts=now,
    )

    synth = VectorSynthesis(test_config, db)

    # No quality adjustment: uses config preset weights.
    res = synth.synthesize(cycle_id="c1", symbol="BTC", as_of=now)

    # Feature snapshot must include vectors for all domains we provided.
    assert set(res.snapshot.features) == {"curator", "onchain", "tradfi", "social", "technical", "events"}

    # Weighted score should be in range.
    assert 0.0 <= res.weighted_score <= 1.0

    # Weight application sanity: if we crush all but curator to 0, composite ~ curator score.
    curator_only = {"curator": 1.0, "onchain": 0.0, "tradfi": 0.0, "social": 0.0, "technical": 0.0, "events": 0.0}
    res2 = synth.synthesize(cycle_id="c2", symbol="BTC", as_of=now, weights=curator_only)
    assert abs(res2.weighted_score - res2.domain_scores["curator"]) < 1e-9


def test_synthesis_missing_domain_degrades_gracefully(test_config, temp_dir):
    db = Database(temp_dir / "brain.db")
    now = datetime.now(tz=UTC)

    # Only technical event present.
    db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "ETH", "rsi_14": 30.0, "trend_strength": 0.9},
        ts=now - timedelta(minutes=5),
    )

    synth = VectorSynthesis(test_config, db)
    res = synth.synthesize(
        cycle_id="c3",
        symbol="ETH",
        as_of=now,
        quality_adjustment={"technical": 1.0, "onchain": 0.0, "tradfi": 0.0, "social": 0.0, "events": 0.0, "curator": 0.0},
    )

    # Snapshot only contains the domains with actual features.
    assert set(res.snapshot.features) == {"technical"}
    assert "technical" in res.domain_scores
    assert res.weighted_score == res.domain_scores["technical"]
