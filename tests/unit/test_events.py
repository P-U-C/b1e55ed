from __future__ import annotations

import json

import pytest

from engine.core.events import (
    ACISignalPayload,
    CuratorSignalPayload,
    EventEnvelope,
    EventType,
    TASignalPayload,
    canonical_json,
    compute_dedupe_key,
)


def test_event_type_enum_contains_expected_members() -> None:
    # Contract: no scattered strings.
    assert EventType.SIGNAL_TA_V1.value == "signal.ta.v1"
    assert EventType.TRADE_INTENT_V1.value.startswith("execution.")
    assert EventType.KARMA_INTENT_V1.value.startswith("karma.")


def test_payload_models_validate() -> None:
    p = TASignalPayload(symbol="BTC", rsi_14=55.0)
    assert p.symbol == "BTC"

    c = CuratorSignalPayload(symbol="SOL", direction="bullish", conviction=7.5, rationale="setup")
    assert c.source == "operator"

    a = ACISignalPayload(symbol="ETH", consensus_score=1.0, models_queried=3, models_responded=3, dispersion=0.1)
    assert a.models_responded == 3


def test_canonical_json_is_stable() -> None:
    a = {"b": 2, "a": 1}
    b = {"a": 1, "b": 2}
    assert canonical_json(a) == canonical_json(b)


def test_compute_dedupe_key_is_deterministic() -> None:
    payload = {"symbol": "BTC", "rsi_14": 50.0}
    k1 = compute_dedupe_key(EventType.SIGNAL_TA_V1, payload)
    k2 = compute_dedupe_key(EventType.SIGNAL_TA_V1, json.loads(canonical_json(payload)))
    assert k1 == k2


def test_event_envelope_model_is_frozen() -> None:
    env = EventEnvelope(
        id="e",
        type=EventType.SIGNAL_TA_V1,
        ts="2026-02-17T00:00:00Z",
        payload={"symbol": "BTC"},
        hash="h",
    )
    with pytest.raises(Exception):
        env.hash = "nope"  # type: ignore[misc]
