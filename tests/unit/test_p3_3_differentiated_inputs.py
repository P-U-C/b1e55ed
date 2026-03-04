from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
import pytest

from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import (
    AbstentionReason,
    OnchainSignalPayload,
    SentimentSignalPayload,
    TASignalPayload,
    TradFiSignalPayload,
)
from engine.core.metrics import MetricsRegistry
from engine.producers.base import ProducerContext
from engine.producers.onchain import OnchainFlowsProducer
from engine.producers.sentiment import MarketSentimentProducer
from engine.producers.ta import TechnicalInterpreter
from engine.producers.tradfi import TradFiBasisInterpreter, _fetch_hl_liquidations


class DummyClient:
    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:  # noqa: ARG002
        raise AssertionError("network request should not be called in normalize tests")

    async def request_json(self, method: str, url: str, **kwargs: Any) -> Any:  # noqa: ARG002
        raise AssertionError("request_json should not be called in normalize tests")


def _ctx(tmp_path, name: str) -> ProducerContext:
    return ProducerContext(
        config=Config(),
        db=Database(tmp_path / f"{name}.db"),
        client=DummyClient(),
        metrics=MetricsRegistry(),
        logger=logging.getLogger("test"),
    )


def test_ta_payload_accepts_new_fields() -> None:
    payload = TASignalPayload(
        symbol="BTC",
        rsi_14=52.0,
        trend="bullish",
        bb_width=0.031,
        atr_14=1200.5,
        volatility_compression=True,
        breakout_failure=False,
    )
    assert payload.symbol == "BTC"
    assert payload.bb_width == 0.031
    assert payload.volatility_compression is True


def test_onchain_payload_accepts_new_flow_fields() -> None:
    payload = OnchainSignalPayload(
        symbol="ETH",
        exchange_flow=-2_000_000,
        flow_direction="outflow",
        flow_magnitude=0.4,
        entity_type="whale",
    )
    assert payload.flow_direction == "outflow"
    assert payload.flow_magnitude == 0.4
    assert payload.entity_type == "whale"


def test_tradfi_payload_accepts_new_liquidation_fields() -> None:
    payload = TradFiSignalPayload(
        symbol="BTC",
        direction="long",
        confidence=0.7,
        smart_money_delta=1_500_000,
        liquidation_cluster_long=20_000_000,
        liquidation_cluster_short=12_000_000,
        liq_asymmetry=0.625,
    )
    assert payload.smart_money_delta == 1_500_000
    assert payload.liquidation_cluster_long == 20_000_000
    assert payload.liq_asymmetry == 0.625


def test_sentiment_payload_accepts_new_positioning_fields() -> None:
    payload = SentimentSignalPayload(
        symbol="SOL",
        fear_greed=78.0,
        long_short_ratio=2.3,
        funding_extreme=True,
        positioning_signal="extreme_long",
    )
    assert payload.long_short_ratio == 2.3
    assert payload.funding_extreme is True
    assert payload.positioning_signal == "extreme_long"


def _ta_signal(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "symbol": "BTC",
        "trend": "bullish",
        "trend_strength": 0.6,
        "rsi_14": 55.0,
        "volatility_compression": False,
        "breakout_failure": False,
    }
    base.update(overrides)
    return base


def test_technical_interpreter_volatility_compression_boosts_confidence() -> None:
    interpreter = TechnicalInterpreter()

    baseline = interpreter.interpret(asset="BTC", horizon="4h", signals=[_ta_signal()])
    boosted = interpreter.interpret(
        asset="BTC",
        horizon="4h",
        signals=[_ta_signal(volatility_compression=True)],
    )

    assert baseline.action == "long"
    assert boosted.action == "long"
    assert boosted.confidence > baseline.confidence


def test_technical_interpreter_breakout_failure_suppresses_confidence() -> None:
    interpreter = TechnicalInterpreter()

    baseline = interpreter.interpret(asset="BTC", horizon="4h", signals=[_ta_signal()])
    suppressed = interpreter.interpret(
        asset="BTC",
        horizon="4h",
        signals=[_ta_signal(breakout_failure=True)],
    )

    assert suppressed.action == "long"
    assert suppressed.confidence < baseline.confidence


def test_technical_interpreter_weak_trend_abstains() -> None:
    interpreter = TechnicalInterpreter()

    payload = interpreter.interpret(
        asset="BTC",
        horizon="4h",
        signals=[_ta_signal(trend_strength=0.2)],
    )

    assert payload.action == "no_forecast"
    assert payload.abstention_reason == AbstentionReason.INSUFFICIENT_DATA


def test_tradfi_interpreter_suppresses_long_when_liq_asymmetry_high() -> None:
    interpreter = TradFiBasisInterpreter()

    payload = interpreter.interpret(
        asset="BTC",
        horizon="4h",
        signals=[
            {
                "symbol": "BTC",
                "direction": "long",
                "confidence": 0.8,
                "signal_reason": "setup",
                "liq_asymmetry": 0.7,
            }
        ],
    )

    assert payload.action == "long"
    assert payload.confidence == pytest.approx(0.68, rel=1e-3)


def test_fetch_hl_liquidations_failure_returns_empty_dict() -> None:
    class FailingClient:
        async def post(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401, ARG002
            raise httpx.TimeoutException("boom")

    result = asyncio.run(_fetch_hl_liquidations(FailingClient(), ["BTC"]))
    assert result == {}


def test_onchain_normalize_sets_outflow_direction(tmp_path) -> None:
    producer = OnchainFlowsProducer(_ctx(tmp_path, "onchain"))

    events = producer.normalize(
        [
            {
                "symbol": "BTC",
                "exchange_flow": -2_500_000,
            }
        ]
    )

    assert len(events) == 1
    payload = events[0].payload
    assert payload["flow_direction"] == "outflow"
    assert payload["flow_magnitude"] == pytest.approx(0.05, rel=1e-3)


def test_sentiment_normalize_sets_extreme_long_from_fear_greed(tmp_path) -> None:
    producer = MarketSentimentProducer(_ctx(tmp_path, "sentiment"))

    events = producer.normalize([{"symbol": "BTC", "fear_greed": 85}])

    assert len(events) == 1
    payload = events[0].payload
    assert payload["positioning_signal"] == "extreme_long"
