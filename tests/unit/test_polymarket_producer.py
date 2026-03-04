from __future__ import annotations

import json
import logging
from unittest.mock import Mock, patch

import httpx
import pytest

from engine.core.client import DataClient
from engine.core.config import Config
from engine.core.database import Database
from engine.core.metrics import MetricsRegistry
from engine.producers.base import ProducerContext
from engine.producers.polymarket import (
    PolymarketProducer,
    _confidence,
    compute_vwap,
    liquidity_tier,
)


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


def _market(
    *,
    market_id: str,
    slug: str,
    probability: float,
    best_bid: float,
    best_ask: float,
    delta_24h: float,
    liquidity: float = 120_000.0,
    volume_24h: float = 10_000.0,
    end_date: str | None = "2026-12-31T00:00:00Z",
) -> dict:
    market = {
        "id": market_id,
        "slug": slug,
        "question": f"Question for {slug}",
        "bestBid": best_bid,
        "bestAsk": best_ask,
        "outcomePrices": json.dumps([str(probability), str(max(0.0, 1.0 - probability))]),
        "oneDayPriceChange": delta_24h,
        "liquidity": liquidity,
        "volume24hr": volume_24h,
    }
    if end_date is not None:
        market["endDate"] = end_date
    return market


def test_compute_vwap_single_level() -> None:
    asks = [(0.41, 800.0)]

    result = compute_vwap(asks, target_usd=500.0)

    assert result == pytest.approx(0.41)


def test_compute_vwap_multi_level() -> None:
    asks = [(0.40, 200.0), (0.50, 300.0), (0.60, 500.0)]

    result = compute_vwap(asks, target_usd=600.0)

    expected = ((0.40 * 200.0) + (0.50 * 300.0) + (0.60 * 100.0)) / 600.0
    assert result == pytest.approx(expected)


def test_compute_vwap_insufficient_depth() -> None:
    asks = [(0.45, 120.0), (0.50, 200.0)]

    result = compute_vwap(asks, target_usd=500.0)

    assert result is None


def test_ev_floor_discards_signal(mock_ctx: ProducerContext) -> None:
    producer = PolymarketProducer(mock_ctx)
    raw = [
        _market(
            market_id="m-ev-floor",
            slug="will-the-fed-cut-rates-in-may-2026",
            probability=0.51,
            best_bid=0.50,
            best_ask=0.52,
            delta_24h=0.01,
        )
    ]

    events = producer.normalize(raw)

    assert events == []


def test_liquidity_tier_boundaries() -> None:
    assert liquidity_tier(49_999.99) == "thin"
    assert liquidity_tier(50_000.0) == "low"
    assert liquidity_tier(499_999.99) == "low"
    assert liquidity_tier(500_000.0) == "high"


def test_p_true_method_momentum(mock_ctx: ProducerContext) -> None:
    producer = PolymarketProducer(mock_ctx)
    raw = [
        _market(
            market_id="m-momentum",
            slug="will-the-fed-cut-rates-in-march-2026",
            probability=0.50,
            best_bid=0.50,
            best_ask=0.50,
            delta_24h=0.10,
            liquidity=700_000.0,
        )
    ]

    events = producer.normalize(raw)

    assert len(events) == 1
    payload = events[0].payload
    assert payload["p_true_method"] == "momentum"
    assert payload["p_true_estimate"] == pytest.approx(0.55)
    assert payload["ev"] == pytest.approx(0.05)


def test_p_true_method_market_price_fallback(mock_ctx: ProducerContext) -> None:
    producer = PolymarketProducer(mock_ctx)
    raw = [
        _market(
            market_id="m-market-price",
            slug="will-ethereum-reach-5000-in-2026",
            probability=0.55,
            best_bid=0.70,
            best_ask=0.40,
            delta_24h=0.02,
        )
    ]

    events = producer.normalize(raw)

    assert len(events) == 1
    payload = events[0].payload
    assert payload["p_true_method"] == "market_price"
    assert payload["p_true_estimate"] == pytest.approx((0.70 + 0.40) / 2.0)


def test_payload_completeness(mock_ctx: ProducerContext) -> None:
    producer = PolymarketProducer(mock_ctx)
    raw = [
        _market(
            market_id="m-payload",
            slug="will-the-fed-cut-rates-in-march-2026",
            probability=0.53,
            best_bid=0.50,
            best_ask=0.50,
            delta_24h=0.10,
            liquidity=650_000.0,
            volume_24h=250_000.0,
        )
    ]

    events = producer.normalize(raw)

    assert len(events) == 1
    payload = events[0].payload

    required_fields = {
        "contract",
        "category",
        "liquidity_tier",
        "mid_price",
        "executable_price",
        "p_true_estimate",
        "p_true_method",
        "ev",
        "ev_return_rate",
        "spread_cost",
        "probability",
        "probability_delta_24h",
        "volume_24h_usd",
        "liquidity_usd",
        "resolves_at",
        "signal",
        "confidence",
        "reason",
        "direction",
    }

    assert required_fields.issubset(payload.keys())


def test_resolves_at_extracted(mock_ctx: ProducerContext) -> None:
    producer = PolymarketProducer(mock_ctx)
    end_date = "2026-05-15T12:00:00Z"
    raw = [
        _market(
            market_id="m-resolve",
            slug="will-bitcoin-reach-100000-in-2026",
            probability=0.50,
            best_bid=0.50,
            best_ask=0.50,
            delta_24h=0.09,
            end_date=end_date,
        )
    ]

    events = producer.normalize(raw)

    assert len(events) == 1
    assert events[0].payload["resolves_at"] == end_date


def test_network_error_returns_empty(mock_ctx: ProducerContext) -> None:
    producer = PolymarketProducer(mock_ctx)

    with patch("engine.producers.polymarket.httpx.Client") as mock_client_cls:
        client = mock_client_cls.return_value.__enter__.return_value
        client.get.side_effect = httpx.ConnectError("network down")

        assert producer.collect() == []


def test_confidence_formula() -> None:
    assert _confidence(600_000.0, 0.10, "momentum") == pytest.approx(0.8)
    assert _confidence(100_000.0, 0.04, "market_price") == pytest.approx(0.32)
    assert _confidence(10_000.0, 0.20, "cross_platform_discrepancy") == pytest.approx(0.6)
