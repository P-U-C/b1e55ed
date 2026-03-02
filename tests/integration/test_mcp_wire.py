"""Integration tests: all producers register with MCPProducerRegistry on init."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import engine.mcp.registry as registry_module
from engine.core.events import EventType
from engine.mcp.registry import MCPProducerRegistry, get_registry
from engine.producers.aci import ACIProducer
from engine.producers.base import BaseProducer
from engine.producers.curator import CuratorIntelProducer
from engine.producers.etf import ETFFlowsProducer
from engine.producers.events import MarketEventsProducer
from engine.producers.financial_datasets import FinancialDatasetsMCPProducer
from engine.producers.onchain import OnchainFlowsProducer as OnchainProducer
from engine.producers.orderbook import OrderbookDepthProducer
from engine.producers.price_ws import PriceAlertsProducer
from engine.producers.sentiment import MarketSentimentProducer as SentimentProducer
from engine.producers.social import SocialIntelProducer
from engine.producers.stablecoin import StablecoinSupplyProducer
from engine.producers.ta import TechnicalAnalysisProducer as TaProducer
from engine.producers.tradfi import TradFiBasisProducer
from engine.producers.whale import WhaleTrackingProducer


@pytest.fixture(autouse=True)
def fresh_registry(monkeypatch):
    """Reset MCP singleton state for each test."""

    registry = MCPProducerRegistry()
    monkeypatch.setattr(registry_module, "_REGISTRY", registry)
    yield registry


@pytest.fixture()
def mock_producer_context():
    """Mock ProducerContext with all expected fields."""

    ctx = SimpleNamespace(
        config=MagicMock(name="config"),
        db=MagicMock(name="db"),
        client=MagicMock(name="client"),
        metrics=MagicMock(name="metrics"),
        logger=MagicMock(name="logger"),
    )
    ctx.config.universe = SimpleNamespace(symbols=["BTC", "ETH"])
    return ctx


def test_producers_register_with_mcp(mock_producer_context):
    _ = TaProducer(mock_producer_context)
    _ = OnchainProducer(mock_producer_context)
    _ = SentimentProducer(mock_producer_context)

    registry = get_registry()
    registered_names = {manifest.name for manifest in registry.list_producers()}

    assert TaProducer.name in registered_names
    assert OnchainProducer.name in registered_names
    assert SentimentProducer.name in registered_names
    assert registry.stats()["producer_count"] >= 3


def test_publish_pushes_to_mcp(mock_producer_context):
    class MockProducer(BaseProducer):
        name = "mock-producer"
        domain = "technical"
        schedule = "continuous"

        def collect(self) -> list[dict]:
            return []

        def normalize(self, raw: list[dict]):
            return []

    producer = MockProducer(mock_producer_context)
    event = producer.draft_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={
            "symbol": "BTC",
            "direction": "long",
            "confidence": 0.91,
            "reason": "test signal",
        },
    )

    producer.publish([event])

    latest = get_registry().get_latest(producer.name)
    assert latest is not None
    assert latest.producer == producer.name


def test_all_producers_have_mcp_source_url_attr():
    producer_classes = [
        ACIProducer,
        CuratorIntelProducer,
        ETFFlowsProducer,
        MarketEventsProducer,
        OnchainProducer,
        OrderbookDepthProducer,
        PriceAlertsProducer,
        SentimentProducer,
        SocialIntelProducer,
        StablecoinSupplyProducer,
        TaProducer,
        TradFiBasisProducer,
        WhaleTrackingProducer,
    ]

    for producer_class in producer_classes:
        assert hasattr(producer_class, "mcp_source_url"), f"{producer_class.__name__} missing mcp_source_url"


def test_mcp_source_url_financial_datasets():
    assert FinancialDatasetsMCPProducer.mcp_source_url is not None


def test_registry_survives_multiple_inits(mock_producer_context):
    _ = TaProducer(mock_producer_context)
    _ = TaProducer(mock_producer_context)

    manifests = get_registry().list_producers()
    names = [manifest.name for manifest in manifests]

    assert names.count(TaProducer.name) == 1
    assert get_registry().stats()["producer_count"] == 1


def test_signal_buffer_fills_on_publish(mock_producer_context):
    class MockProducer(BaseProducer):
        name = "mock-buffer-producer"
        domain = "technical"
        schedule = "continuous"

        def collect(self) -> list[dict]:
            return []

        def normalize(self, raw: list[dict]):
            return []

    producer = MockProducer(mock_producer_context)
    events = [
        producer.draft_event(
            event_type=EventType.SIGNAL_TA_V1,
            payload={
                "symbol": "BTC",
                "direction": "long",
                "confidence": 0.5,
                "reason": f"signal-{i}",
            },
        )
        for i in range(5)
    ]

    producer.publish(events)

    recent = get_registry().get_recent(producer.name, n=10)
    assert len(recent) == 5
