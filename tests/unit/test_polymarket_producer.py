from __future__ import annotations

import math

import httpx

from engine.core.events import EventType
from engine.producers.polymarket import PolymarketProducer


class _FailingClient:
    def __init__(self, *args, **kwargs) -> None:  # noqa: ARG002
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001, ARG002
        return False

    def get(self, *args, **kwargs):  # noqa: ANN002, ANN003, ARG002
        raise httpx.ConnectError("network down")


class _BadJSONClient:
    def __init__(self, *args, **kwargs) -> None:  # noqa: ARG002
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001, ARG002
        return False

    def get(self, url: str, **kwargs):  # noqa: ANN003, ARG002
        return httpx.Response(200, content=b"not-json", request=httpx.Request("GET", url))


def _producer() -> PolymarketProducer:
    return PolymarketProducer.__new__(PolymarketProducer)


def test_collect_returns_empty_on_network_error(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "Client", _FailingClient)

    producer = _producer()
    assert producer.collect() == []


def test_collect_returns_empty_on_bad_json(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "Client", _BadJSONClient)

    producer = _producer()
    assert producer.collect() == []


def test_normalize_risk_on_fed_cut() -> None:
    producer = _producer()
    raw = [
        {
            "id": "1",
            "slug": "will-the-fed-cut-rates-in-march-2026",
            "question": "Will the Fed cut rates in March 2026?",
            "outcomePrices": '["0.72", "0.28"]',
            "liquidity": 1_000_000,
            "volume24hr": 50_000,
        }
    ]

    events = producer.normalize(raw)

    assert len(events) == 1
    assert events[0].type == EventType.SIGNAL_EVENTS_V1
    assert events[0].payload["signal"] == "risk_on"
    assert events[0].payload["probability"] == 0.72


def test_normalize_risk_off_fed_cut() -> None:
    producer = _producer()
    raw = [
        {
            "id": "2",
            "slug": "will-the-fed-cut-rates-in-may-2026",
            "question": "Will the Fed cut rates in May 2026?",
            "outcomePrices": '["0.20", "0.80"]',
            "liquidity": 750_000,
        }
    ]

    events = producer.normalize(raw)

    assert len(events) == 1
    assert events[0].payload["signal"] == "risk_off"


def test_normalize_neutral() -> None:
    producer = _producer()
    raw = [
        {
            "id": "3",
            "slug": "federal-reserve-rate-cut-2026",
            "question": "Will the Federal Reserve cut rates in 2026?",
            "outcomePrices": '["0.50", "0.50"]',
            "liquidity": 500_000,
        }
    ]

    events = producer.normalize(raw)

    assert len(events) == 1
    assert events[0].payload["signal"] == "neutral"


def test_confidence_scales_with_liquidity() -> None:
    producer = _producer()
    raw = [
        {
            "id": "4",
            "slug": "will-bitcoin-reach-100000-in-2026",
            "question": "Will Bitcoin reach $100,000 in 2026?",
            "outcomePrices": '["0.70", "0.30"]',
            "liquidity": 10,
        }
    ]

    events = producer.normalize(raw)

    assert len(events) == 1
    expected = min(1.0, math.log10(max(1.0, 10.0)) / 6)
    assert events[0].payload["confidence"] == expected
    assert events[0].payload["confidence"] < 0.2


def test_normalize_returns_empty_on_malformed_prices() -> None:
    producer = _producer()
    raw = [
        {
            "id": "5",
            "slug": "will-bitcoin-reach-100000-in-2026",
            "question": "Will Bitcoin reach $100,000 in 2026?",
            "outcomePrices": "not-json",
            "liquidity": 1_000,
        }
    ]

    assert producer.normalize(raw) == []


def test_producer_attributes() -> None:
    producer = _producer()

    assert producer.name == "polymarket"
    assert producer.domain == "events"
    assert producer.schedule == "*/15 * * * *"
    assert producer.mcp_source_url is None
    assert producer.assets == []
