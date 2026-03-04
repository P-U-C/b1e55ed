"""Tests for flywheel S0 — schema foundation."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from engine.core.events import (
    AttributionOutcomePayload,
    EventType,
    ProducerOutcome,
    SignalAcceptedPayload,
    payload_model_for,
)
from engine.core.types import ConvictionScore, TradeIntent


class TestEventTypes:
    def test_attribution_outcome_event_type_exists(self):
        assert EventType.ATTRIBUTION_OUTCOME_V1 == "attribution.outcome.v1"

    def test_signal_accepted_registered(self):
        assert payload_model_for(EventType.SIGNAL_ACCEPTED_V1) is SignalAcceptedPayload

    def test_attribution_outcome_registered(self):
        assert payload_model_for(EventType.ATTRIBUTION_OUTCOME_V1) is AttributionOutcomePayload


class TestSignalAcceptedPayload:
    def test_valid_payload(self):
        p = SignalAcceptedPayload(
            trade_id="t1",
            producer_id="p1",
            domain="tradfi",
            signal_event_id="e1",
            direction="long",
            confidence=0.7,
        )
        assert p.contribution_weight == 1.0
        assert p.horizon is None

    def test_optional_fields(self):
        p = SignalAcceptedPayload(
            trade_id="t1",
            producer_id="p1",
            domain="tradfi",
            signal_event_id="e1",
            direction="long",
            confidence=0.7,
            horizon="4h",
            invalidation=50000.0,
        )
        assert p.horizon == "4h"
        assert p.invalidation == 50000.0


class TestAttributionOutcomePayload:
    def test_valid_payload(self):
        p = AttributionOutcomePayload(
            trade_id="t1",
            realized_pnl_usd=100.0,
            confidence_bucket="high",
            producers=[
                ProducerOutcome(
                    producer_id="p1",
                    domain="tradfi",
                    contribution_weight=1.0,
                    outcome=1.0,
                    karma_delta=0.05,
                )
            ],
        )
        assert p.confidence_bucket == "high"
        assert len(p.producers) == 1

    def test_invalid_confidence_bucket(self):
        with pytest.raises(ValidationError):
            AttributionOutcomePayload(
                trade_id="t1",
                realized_pnl_usd=100.0,
                confidence_bucket="invalid",
                producers=[],
            )


class TestTypesHorizonInvalidation:
    def test_conviction_score_new_fields(self):
        cs = ConvictionScore(
            node_id="n1",
            symbol="BTC",
            direction="long",
            magnitude=5.0,
            timeframe="4h",
            ts=datetime.now(),
            commitment_hash="abc",
            horizon="4h",
            invalidation=50000.0,
        )
        assert cs.horizon == "4h"
        assert cs.invalidation == 50000.0

    def test_conviction_score_defaults_none(self):
        cs = ConvictionScore(
            node_id="n1",
            symbol="BTC",
            direction="long",
            magnitude=5.0,
            timeframe="4h",
            ts=datetime.now(),
            commitment_hash="abc",
        )
        assert cs.horizon is None
        assert cs.invalidation is None

    def test_trade_intent_new_fields(self):
        ti = TradeIntent(
            symbol="BTC",
            direction="long",
            size_pct=1.0,
            leverage=1.0,
            conviction_score=0.7,
            regime="risk_on",
            rationale="test",
            horizon="4h",
            invalidation=50000.0,
        )
        assert ti.horizon == "4h"
        assert ti.invalidation == 50000.0

    def test_trade_intent_defaults_none(self):
        ti = TradeIntent(
            symbol="BTC",
            direction="long",
            size_pct=1.0,
            leverage=1.0,
            conviction_score=0.7,
            regime="risk_on",
            rationale="test",
        )
        assert ti.horizon is None
        assert ti.invalidation is None
