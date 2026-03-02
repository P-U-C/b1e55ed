"""Tests for FORECAST_V1 schema and helpers."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from engine.core.events import (
    _EVENT_PAYLOAD_MODELS,
    AbstentionReason,
    EventType,
    ForecastLifecycleState,
    ForecastPayload,
)
from engine.core.forecast import abstain, compute_reasoning_hash, make_forecast_id


def test_forecast_event_type_exists() -> None:
    assert EventType.FORECAST_V1 == "forecast.v1"


def test_forecast_payload_construction_with_all_fields() -> None:
    payload = ForecastPayload(
        forecast_id="a499f9f5-d6d0-4f68-b6ea-2fd4f84e74fe",
        protocol_version="1.0",
        asset="BTC",
        horizon="4h",
        action="long",
        confidence=0.73,
        calibrated=True,
        invalidation=92000.0,
        regime_tag="risk-on",
        crisis_state=False,
        reasoning_hash="abc123",
        source="producer.alpha@1.2.0",
        lifecycle_state=ForecastLifecycleState.SUPERSEDE,
        supersedes_forecast_id="74a26766-2874-4f6b-89eb-b5f8ceea96ec",
        visible_signal_refs=["evt-1", "evt-2"],
        used_signal_refs=["evt-2"],
    )

    assert payload.asset == "BTC"
    assert payload.lifecycle_state == ForecastLifecycleState.SUPERSEDE
    assert payload.visible_signal_refs == ["evt-1", "evt-2"]
    assert payload.abstention_reason is None


def test_no_forecast_requires_abstention_reason() -> None:
    with pytest.raises(ValidationError):
        ForecastPayload(
            forecast_id="ec9a4890-5682-4fe8-b6a8-67333de4dc86",
            asset="ETH",
            horizon="1h",
            action="no_forecast",
            confidence=0.0,
            source="producer.beta@0.1.0",
        )


def test_no_forecast_with_abstention_reason_is_valid() -> None:
    payload = ForecastPayload(
        forecast_id="76797297-a500-43e5-b1ba-f2738eb2fb8f",
        asset="SOL",
        horizon="24h",
        action="no_forecast",
        confidence=0.0,
        source="producer.gamma@2.0.0",
        abstention_reason=AbstentionReason.INSUFFICIENT_DATA,
    )

    assert payload.abstention_reason == AbstentionReason.INSUFFICIENT_DATA


def test_compute_reasoning_hash_is_deterministic() -> None:
    candidate = {"asset": "BTC", "action": "long", "confidence": 0.7}
    h1 = compute_reasoning_hash(candidate, critique="ok", rationale="trend + flows")
    h2 = compute_reasoning_hash(candidate, critique="ok", rationale="trend + flows")
    assert h1 == h2


def test_compute_reasoning_hash_changes_when_input_changes() -> None:
    candidate = {"asset": "BTC", "action": "long", "confidence": 0.7}
    h1 = compute_reasoning_hash(candidate, critique="ok", rationale="trend + flows")
    h2 = compute_reasoning_hash(candidate, critique="changed", rationale="trend + flows")
    assert h1 != h2


def test_abstain_helper_returns_valid_payload() -> None:
    payload = abstain(
        source="producer.delta@1.0.0",
        asset="BTC",
        horizon="4h",
        reason=AbstentionReason.REGIME_MISMATCH,
        visible_signal_refs=["evt-a", "evt-b"],
    )

    assert isinstance(payload, ForecastPayload)
    assert payload.action == "no_forecast"
    assert payload.abstention_reason == AbstentionReason.REGIME_MISMATCH
    assert payload.lifecycle_state == ForecastLifecycleState.NEW
    assert payload.visible_signal_refs == ["evt-a", "evt-b"]
    assert payload.used_signal_refs == []


def test_forecast_payload_registered_in_event_payload_models() -> None:
    assert _EVENT_PAYLOAD_MODELS[EventType.FORECAST_V1] is ForecastPayload


def test_lifecycle_state_defaults_to_new() -> None:
    payload = ForecastPayload(
        forecast_id="8d9b4bb4-ab29-45f7-a2fc-6908046074ce",
        asset="BTC",
        horizon="4h",
        action="flat",
        confidence=0.5,
        source="producer.epsilon@0.0.1",
    )
    assert payload.lifecycle_state == ForecastLifecycleState.NEW


def test_calibrated_defaults_to_false() -> None:
    payload = ForecastPayload(
        forecast_id="7221e71f-b7c6-45d4-8f4f-b03de8bf57df",
        asset="ETH",
        horizon="1h",
        action="short",
        confidence=0.6,
        source="producer.zeta@3.4.5",
    )
    assert payload.calibrated is False


def test_make_forecast_id_returns_uuid4_string() -> None:
    forecast_id = make_forecast_id()
    parsed = uuid.UUID(forecast_id)
    assert str(parsed) == forecast_id
    assert parsed.version == 4
