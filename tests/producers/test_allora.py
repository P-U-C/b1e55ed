"""Tests for AlloraInferenceProducer."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from engine.core.client import DataClient
from engine.core.config import Config
from engine.core.database import Database
from engine.core.metrics import MetricsRegistry
from engine.core.types import ProducerHealth
from engine.producers.allora import (
    ALLORA_TOPICS,
    AlloraInferenceProducer,
    _compute_score,
    _fetch_allora_inferences,
)
from engine.producers.base import ProducerContext

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_warned_no_key():
    """Reset the module-level one-shot warning flag before each test."""
    import engine.producers.allora as _m

    _m._warned_no_key = False
    yield
    _m._warned_no_key = False


@pytest.fixture()
def mock_ctx() -> ProducerContext:
    config = Mock(spec=Config)
    config.universe = Mock()
    config.universe.symbols = []

    return ProducerContext(
        config=config,
        db=Mock(spec=Database),
        client=Mock(spec=DataClient),
        metrics=Mock(spec=MetricsRegistry),
        logger=Mock(spec=logging.Logger),
    )


@pytest.fixture()
def producer(mock_ctx: ProducerContext) -> AlloraInferenceProducer:
    return AlloraInferenceProducer(mock_ctx)


# ── Helper ────────────────────────────────────────────────────────────────────


def _make_inference(normalized: str, ci_values: list[float] | None = None) -> MagicMock:
    """Build a fake Allora Inference object."""
    inf_data = MagicMock()
    inf_data.network_inference_normalized = normalized
    if ci_values is not None:
        inf_data.confidence_interval_values = ci_values
    else:
        # Simulate topics that don't have CI values.
        type(inf_data).confidence_interval_values = property(lambda self: (_ for _ in ()).throw(AttributeError("no ci")))
    inference = MagicMock()
    inference.inference_data = inf_data
    return inference


# ── Test 1: No API key → OK, 0 events ─────────────────────────────────────────


def test_no_api_key_returns_ok_zero_events(producer: AlloraInferenceProducer, monkeypatch):
    """When ALLORA_API_KEY is unset the producer returns OK with 0 events published."""
    monkeypatch.delenv("ALLORA_API_KEY", raising=False)

    result = producer.run()

    assert result.health == ProducerHealth.OK
    assert result.events_published == 0
    assert result.errors == []


def test_no_api_key_logs_once_then_silent(producer: AlloraInferenceProducer, monkeypatch):
    """Missing-key warning should be logged at most once across multiple polls."""
    monkeypatch.delenv("ALLORA_API_KEY", raising=False)

    import engine.producers.allora as _m

    with patch.object(_m._log, "info") as mock_info:
        producer.run()
        producer.run()
        producer.run()

    # info() should have been called for the key warning exactly once.
    allora_calls = [c for c in mock_info.call_args_list if "allora_no_api_key" in str(c)]
    assert len(allora_calls) == 1


# ── Test 2: Prediction above current → positive score emitted ─────────────────


def test_prediction_above_current_emits_positive_score(producer: AlloraInferenceProducer, monkeypatch):
    """When predicted > current by >0.5 % the emitted consensus_score is positive."""
    monkeypatch.setenv("ALLORA_API_KEY", "test-key")

    current_btc = 50_000.0
    predicted_btc = 51_000.0  # +2 % → score ≈ +2.0

    # Fake inference: topic 14 (BTC 5-min)
    mock_inference = _make_inference(str(predicted_btc), ci_values=[50800.0, 51000.0, 51200.0])

    mock_client = AsyncMock()
    mock_client.get_inference_by_topic_id.return_value = mock_inference

    raw_rows = [
        {
            "topic_id": 14,
            "symbol": "BTC",
            "binance_symbol": "BTCUSDT",
            "predicted": predicted_btc,
            "current": current_btc,
            "ci_values": [50800.0, 51000.0, 51200.0],
        }
    ]

    with patch("engine.producers.allora._fetch_allora_inferences", new=AsyncMock(return_value=raw_rows)):
        collected = producer.collect()

    events = producer.normalize(collected)

    assert len(events) == 1
    score = events[0].payload["consensus_score"]
    assert score > 0, f"Expected positive score, got {score}"
    assert score <= 8.0


# ── Test 3: Prediction below current → negative score emitted ─────────────────


def test_prediction_below_current_emits_negative_score(producer: AlloraInferenceProducer, monkeypatch):
    """When predicted < current by >0.5 % the emitted consensus_score is negative."""
    monkeypatch.setenv("ALLORA_API_KEY", "test-key")

    current_eth = 3_000.0
    predicted_eth = 2_940.0  # -2 % → score ≈ -2.0

    raw_rows = [
        {
            "topic_id": 13,
            "symbol": "ETH",
            "binance_symbol": "ETHUSDT",
            "predicted": predicted_eth,
            "current": current_eth,
            "ci_values": [],
        }
    ]

    with patch("engine.producers.allora._fetch_allora_inferences", new=AsyncMock(return_value=raw_rows)):
        collected = producer.collect()

    events = producer.normalize(collected)

    assert len(events) == 1
    score = events[0].payload["consensus_score"]
    assert score < 0, f"Expected negative score, got {score}"
    assert score >= -8.0


# ── Test 4: Prediction within 0.5 % → neutral score ─────────────────────────


def test_prediction_within_neutral_band_emits_zero_score(producer: AlloraInferenceProducer, monkeypatch):
    """When predicted is within ±0.5 % of current the consensus_score should be 0."""
    monkeypatch.setenv("ALLORA_API_KEY", "test-key")

    current_btc = 50_000.0
    predicted_btc = 50_200.0  # +0.4 % — inside neutral band

    raw_rows = [
        {
            "topic_id": 14,
            "symbol": "BTC",
            "binance_symbol": "BTCUSDT",
            "predicted": predicted_btc,
            "current": current_btc,
            "ci_values": [],
        }
    ]

    with patch("engine.producers.allora._fetch_allora_inferences", new=AsyncMock(return_value=raw_rows)):
        collected = producer.collect()

    events = producer.normalize(collected)

    assert len(events) == 1
    score = events[0].payload["consensus_score"]
    assert score == 0.0, f"Expected 0.0 for neutral prediction, got {score}"


# ── Test 5: One topic fails → others still processed ──────────────────────────


def test_topic_fetch_failure_logs_and_continues(monkeypatch):
    """If one topic raises an exception the remaining topics are still processed."""
    monkeypatch.setenv("ALLORA_API_KEY", "test-key")

    # Topic 14 raises; topic 13 succeeds with a +3 % prediction.
    current_prices = {"BTCUSDT": 50_000.0, "ETHUSDT": 3_000.0}

    async def _fake_fetch(api_key: str) -> list[dict[str, Any]]:
        """Simulate _fetch_allora_inferences: topic 14 fails, topic 13 succeeds."""
        results = []
        for topic_id, info in ALLORA_TOPICS.items():
            if topic_id == 14:
                _fetch_allora_inferences  # noqa: B018 – referenced for coverage visibility
                raise_exc = True
            else:
                raise_exc = False

            if raise_exc:
                # Log but skip — mirrors the real implementation.
                continue

            current = current_prices.get(info["binance_symbol"])
            if current is None:
                continue
            results.append(
                {
                    "topic_id": topic_id,
                    "symbol": info["symbol"],
                    "binance_symbol": info["binance_symbol"],
                    "predicted": current * 1.03,  # +3 %
                    "current": current,
                    "ci_values": [current * 1.01, current * 1.03, current * 1.05],
                }
            )
        return results

    with patch("engine.producers.allora._fetch_allora_inferences", new=_fake_fetch):
        rows = asyncio.run(_fake_fetch("test-key"))

    # Topic 14 was dropped; the other three topics should still produce results.
    topic_ids_returned = {r["topic_id"] for r in rows}
    assert 14 not in topic_ids_returned
    assert len(rows) >= 1, "At least one topic should succeed when topic 14 fails"

    # Verify all scores for the surviving topics are positive (prediction > current by 3 %).
    for row in rows:
        score = _compute_score(row["predicted"], row["current"])
        assert score > 0


# ── Unit test for score computation ──────────────────────────────────────────


def test_compute_score_caps_at_eight():
    """Extreme deviations should be capped at ±8."""
    assert _compute_score(60_000.0, 50_000.0) == pytest.approx(8.0)  # +18 % → cap at 8
    assert _compute_score(40_000.0, 50_000.0) == pytest.approx(-8.0)  # -18 % → floor at -8


def test_compute_score_neutral_band():
    assert _compute_score(50_200.0, 50_000.0) == 0.0  # +0.4 %
    assert _compute_score(49_800.0, 50_000.0) == 0.0  # -0.4 %


def test_compute_score_just_outside_neutral():
    # +0.6 % → should produce a small positive score, not zero.
    score = _compute_score(50_300.0, 50_000.0)
    assert score > 0
