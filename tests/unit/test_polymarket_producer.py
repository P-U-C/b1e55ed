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
from engine.producers.polymarket import PolymarketProducer


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


def _market(*, market_id: str, slug: str, probability: float, liquidity: float = 10_000.0, volume_24h: float = 1_000.0) -> dict:
    return {
        "id": market_id,
        "slug": slug,
        "question": f"Question for {slug}",
        "outcomePrices": json.dumps([str(probability), str(max(0.0, 1.0 - probability))]),
        "liquidity": liquidity,
        "volume24hr": volume_24h,
    }


def test_producer_attrs() -> None:
    assert PolymarketProducer.name == "polymarket"
    assert PolymarketProducer.domain == "events"
    assert PolymarketProducer.schedule == "*/15 * * * *"
    assert PolymarketProducer.mcp_source_url is None


def test_collect_returns_empty_on_network_error(mock_ctx: ProducerContext) -> None:
    producer = PolymarketProducer(mock_ctx)

    with patch("engine.producers.polymarket.httpx.Client") as mock_client_cls:
        client = mock_client_cls.return_value.__enter__.return_value
        client.get.side_effect = httpx.ConnectError("network down")

        assert producer.collect() == []

    mock_client_cls.assert_called_once_with(timeout=producer.TIMEOUT)


def test_collect_returns_empty_on_bad_json(mock_ctx: ProducerContext) -> None:
    producer = PolymarketProducer(mock_ctx)

    bad_json_response = httpx.Response(
        200,
        content="not-json",
        request=httpx.Request("GET", f"{producer.GAMMA_BASE}/markets"),
    )

    with patch("engine.producers.polymarket.httpx.Client") as mock_client_cls:
        client = mock_client_cls.return_value.__enter__.return_value
        client.get.return_value = bad_json_response

        assert producer.collect() == []


def test_normalize_risk_on_fed(mock_ctx: ProducerContext) -> None:
    producer = PolymarketProducer(mock_ctx)
    raw = [_market(market_id="1", slug="will-the-fed-cut-rates-in-may-2026", probability=0.75)]

    events = producer.normalize(raw)

    assert len(events) == 1
    payload = events[0].payload
    assert payload["signal"] == "risk_on"
    assert payload["direction"] == "risk_on"


def test_normalize_risk_off_fed(mock_ctx: ProducerContext) -> None:
    producer = PolymarketProducer(mock_ctx)
    raw = [_market(market_id="2", slug="will-the-fed-cut-rates-in-march-2026", probability=0.20)]

    events = producer.normalize(raw)

    assert len(events) == 1
    payload = events[0].payload
    assert payload["signal"] == "risk_off"
    assert payload["direction"] == "risk_off"


def test_normalize_neutral_mid(mock_ctx: ProducerContext) -> None:
    producer = PolymarketProducer(mock_ctx)
    raw = [_market(market_id="3", slug="will-the-fed-cut-rates-in-march-2026", probability=0.50)]

    events = producer.normalize(raw)

    assert len(events) == 1
    payload = events[0].payload
    assert payload["signal"] == "neutral"
    assert payload["direction"] == "neutral"


def test_confidence_scales_with_liquidity(mock_ctx: ProducerContext) -> None:
    producer = PolymarketProducer(mock_ctx)
    raw = [_market(market_id="4", slug="will-bitcoin-reach-100000-in-2026", probability=0.70, liquidity=0.0)]

    events = producer.normalize(raw)

    assert len(events) == 1
    assert events[0].payload["confidence"] == pytest.approx(0.0)


def test_normalize_skips_malformed_prices(mock_ctx: ProducerContext) -> None:
    producer = PolymarketProducer(mock_ctx)
    raw = [
        {
            "id": "bad-1",
            "slug": "will-bitcoin-reach-100000-in-2026",
            "question": "Malformed prices",
            "outcomePrices": "{not-valid-json}",
            "liquidity": 1000,
            "volume24hr": 100,
        }
    ]

    events = producer.normalize(raw)

    assert events == []
    mock_ctx.logger.warning.assert_called()
