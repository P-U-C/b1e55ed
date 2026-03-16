"""Unit tests for the external adapter framework (Phase 1A / SPI)."""

from __future__ import annotations

import pytest

from engine.external.confidence import normalize_confidence
from engine.external.models import ExternalObservation, RawExternalRecord
from engine.external.policy import AdapterPolicy
from engine.producers.post_fiat_signals import PostFiatSignalsProducer

# ---------------------------------------------------------------------------
# normalize_confidence
# ---------------------------------------------------------------------------


def test_normalize_confidence_direct_none() -> None:
    """None input returns the floor value 0.55."""
    assert normalize_confidence(None) == 0.55


def test_normalize_confidence_direct_clamps_high() -> None:
    """Values above 0.99 are clamped to 0.99."""
    assert normalize_confidence(1.0) == 0.99
    assert normalize_confidence(2.5) == 0.99


def test_normalize_confidence_direct_clamps_low() -> None:
    """Values below 0.55 are raised to 0.55."""
    assert normalize_confidence(0.0) == 0.55
    assert normalize_confidence(0.1) == 0.55


def test_normalize_confidence_direct_passthrough() -> None:
    """Values in the valid range pass through unchanged."""
    assert normalize_confidence(0.75) == pytest.approx(0.75)
    assert normalize_confidence(0.55) == pytest.approx(0.55)
    assert normalize_confidence(0.99) == pytest.approx(0.99)


def test_normalize_confidence_hit_rate_strategy() -> None:
    """hit_rate strategy uses hit_rate as proxy when provided."""
    result = normalize_confidence(0.4, strategy="hit_rate", hit_rate=0.70)
    assert result == pytest.approx(0.70)


def test_normalize_confidence_hit_rate_fallback() -> None:
    """hit_rate strategy falls back to value when hit_rate is None."""
    result = normalize_confidence(0.80, strategy="hit_rate", hit_rate=None)
    assert result == pytest.approx(0.80)


def test_normalize_confidence_unknown_strategy_returns_floor() -> None:
    """Unknown strategy returns floor value."""
    assert normalize_confidence(0.9, strategy="bogus") == 0.55


# ---------------------------------------------------------------------------
# AdapterPolicy.should_skip
# ---------------------------------------------------------------------------


def _make_obs(**kwargs) -> ExternalObservation:
    """Helper: build an ExternalObservation with sensible defaults."""
    defaults: dict = {
        "symbol": "BTC",
        "direction": "bullish",
        "confidence": 0.80,
        "horizon_hours": 168,
        "observed_at": "2025-01-01T00:00:00Z",
        "is_stale": False,
        "health_state": "HEALTHY",
    }
    defaults.update(kwargs)
    return ExternalObservation(**defaults)


def test_policy_skip_halt() -> None:
    """HALT health state always triggers a skip."""
    obs = _make_obs(health_state="HALT")
    policy = AdapterPolicy()
    skip, reason = policy.should_skip(obs)
    assert skip is True
    assert reason == "health_halt"


def test_policy_skip_stale() -> None:
    """Stale observations are skipped."""
    obs = _make_obs(is_stale=True)
    policy = AdapterPolicy()
    skip, reason = policy.should_skip(obs)
    assert skip is True
    assert reason == "stale"


def test_policy_skip_low_confidence() -> None:
    """Observations below min_confidence threshold are skipped."""
    obs = _make_obs(confidence=0.40)
    policy = AdapterPolicy(min_confidence=0.55)
    skip, reason = policy.should_skip(obs)
    assert skip is True
    assert reason == "low_confidence"


def test_policy_no_skip_healthy() -> None:
    """Healthy, fresh, high-confidence observation is not skipped."""
    obs = _make_obs(confidence=0.80, health_state="HEALTHY", is_stale=False)
    policy = AdapterPolicy()
    skip, reason = policy.should_skip(obs)
    assert skip is False
    assert reason == ""


def test_policy_halt_takes_priority_over_stale() -> None:
    """HALT is checked first, even if observation is also stale."""
    obs = _make_obs(health_state="HALT", is_stale=True)
    policy = AdapterPolicy()
    skip, reason = policy.should_skip(obs)
    assert reason == "health_halt"


def test_policy_degraded_not_skipped() -> None:
    """DEGRADED health state does NOT trigger a skip (only HALT does)."""
    obs = _make_obs(health_state="DEGRADED", confidence=0.80, is_stale=False)
    policy = AdapterPolicy()
    skip, _ = policy.should_skip(obs)
    assert skip is False
    assert policy.is_degraded(obs) is True


# ---------------------------------------------------------------------------
# PostFiatSignalsProducer.normalize
# ---------------------------------------------------------------------------


def _make_raw(signals: list[dict], health_status: str = "HEALTHY") -> RawExternalRecord:
    """Helper: wrap signals list in a RawExternalRecord."""
    return RawExternalRecord(
        source_system="post-fiat-signals",
        source_endpoint="/signals/filtered",
        source_payload_hash="abc123",
        adapter_version="1.0.0",
        raw_payload={"signals": signals, "health": {"status": health_status}},
        fetched_at="2025-01-01T00:00:00Z",
    )


# PostFiatSignalsProducer is normally constructed with a ProducerContext,
# but normalize() does not use ctx, so we test it at the class level.
class _BareProducer(PostFiatSignalsProducer):
    """Bare subclass to allow construction without a full ProducerContext."""

    def __init__(self) -> None:  # type: ignore[override]
        # Skip BaseProducer.__init__ entirely — we only need normalize().
        pass


_producer = _BareProducer()


def test_normalize_buy_maps_to_bullish() -> None:
    """BUY action maps to 'bullish' direction."""
    raw = _make_raw([{"ticker": "BTC", "action": "BUY", "confidence": 0.82, "timestamp": "2025-01-01T00:00:00Z"}])
    obs = _producer.normalize(raw)
    assert len(obs) == 1
    assert obs[0].direction == "bullish"
    assert obs[0].symbol == "BTC"


def test_normalize_sell_maps_to_bearish() -> None:
    """SELL action maps to 'bearish' direction."""
    raw = _make_raw([{"ticker": "ETH", "action": "SELL", "confidence": 0.65, "timestamp": "2025-01-01T00:00:00Z"}])
    obs = _producer.normalize(raw)
    assert obs[0].direction == "bearish"


def test_normalize_hold_maps_to_neutral() -> None:
    """HOLD action maps to 'neutral' direction."""
    raw = _make_raw([{"ticker": "SOL", "action": "HOLD", "confidence": 0.60, "timestamp": "2025-01-01T00:00:00Z"}])
    obs = _producer.normalize(raw)
    assert obs[0].direction == "neutral"


def test_normalize_unknown_action_maps_to_neutral() -> None:
    """Unrecognised action defaults to 'neutral'."""
    raw = _make_raw([{"ticker": "SOL", "action": "WAIT", "confidence": 0.60, "timestamp": "2025-01-01T00:00:00Z"}])
    obs = _producer.normalize(raw)
    assert obs[0].direction == "neutral"


def test_normalize_horizon_is_168() -> None:
    """Post-fiat signals always use 168h (weekly) horizon."""
    raw = _make_raw([{"ticker": "BTC", "action": "BUY", "confidence": 0.7, "timestamp": "2025-01-01T00:00:00Z"}])
    obs = _producer.normalize(raw)
    assert obs[0].horizon_hours == 168


def test_normalize_health_state_propagated() -> None:
    """Health state from the response envelope is propagated to each observation."""
    raw = _make_raw(
        [{"ticker": "BTC", "action": "BUY", "confidence": 0.7, "timestamp": "2025-01-01T00:00:00Z"}],
        health_status="DEGRADED",
    )
    obs = _producer.normalize(raw)
    assert obs[0].health_state == "DEGRADED"


def test_normalize_optional_fields() -> None:
    """Optional fields (regime, hit_rate, etc.) are parsed correctly."""
    signal = {
        "ticker": "BTC",
        "action": "BUY",
        "confidence": 0.85,
        "timestamp": "2025-01-01T00:00:00Z",
        "regime": "bull",
        "signal_type": "momentum",
        "hit_rate": 0.67,
        "avg_return": 0.12,
        "is_stale": False,
    }
    raw = _make_raw([signal])
    obs = _producer.normalize(raw)
    assert obs[0].regime == "bull"
    assert obs[0].signal_type == "momentum"
    assert obs[0].hit_rate == pytest.approx(0.67)
    assert obs[0].avg_return == pytest.approx(0.12)
    assert obs[0].is_stale is False


def test_normalize_empty_signals() -> None:
    """Empty signal list returns empty observations."""
    raw = _make_raw([])
    obs = _producer.normalize(raw)
    assert obs == []
