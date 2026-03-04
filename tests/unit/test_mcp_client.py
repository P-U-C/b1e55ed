from __future__ import annotations

import logging

import httpx

from engine.core.client import DataClient
from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType
from engine.core.metrics import MetricsRegistry
from engine.mcp.client import HttpMCPClient, MCPToolResult
from engine.producers.base import BaseProducer, ProducerContext
from engine.producers.financial_datasets import FinancialDatasetsMCPProducer


class _DummyProducer(BaseProducer):
    name = "dummy"
    domain = "events"
    schedule = "continuous"

    def collect(self) -> list[dict]:
        return []

    def normalize(self, raw: list[dict]):
        return []


def _ctx(tmp_path) -> ProducerContext:
    return ProducerContext(
        config=Config(),
        db=Database(tmp_path / "events.db"),
        client=DataClient(),
        metrics=MetricsRegistry(),
        logger=logging.getLogger("test"),
    )


def test_mcp_tool_result_creation() -> None:
    result = MCPToolResult(
        tool="get_signals",
        data=[{"ticker": "NVDA"}],
        source_url="https://example.test",
        fetched_at="2026-03-01T00:00:00+00:00",
        raw={"data": [{"ticker": "NVDA"}]},
    )

    assert result.tool == "get_signals"
    assert result.data == [{"ticker": "NVDA"}]
    assert result.source_url == "https://example.test"


def test_http_mcp_client_falls_back_to_get_on_405(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        def post(self, url: str, json: dict):
            del json
            calls.append(("POST", url))
            return httpx.Response(405, request=httpx.Request("POST", url))

        def get(self, url: str, params: dict):
            del params
            calls.append(("GET", url))
            return httpx.Response(200, json={"data": [{"ticker": "NVDA"}]}, request=httpx.Request("GET", url))

        def head(self, url: str):
            return httpx.Response(200, request=httpx.Request("HEAD", url))

    monkeypatch.setattr("engine.mcp.client.httpx.Client", FakeClient)

    client = HttpMCPClient(base_url="https://example.test", api_key="k")
    result = client.call_tool("financials/income-statements/", {"ticker": "NVDA"})

    assert result.data == [{"ticker": "NVDA"}]
    assert calls[0] == ("POST", "https://example.test/tools/financials/income-statements")
    assert calls[1] == ("GET", "https://example.test/financials/income-statements")


def test_collect_via_mcp_returns_empty_without_client(tmp_path) -> None:
    producer = _DummyProducer(_ctx(tmp_path))
    producer._mcp_client = None

    assert producer._collect_via_mcp() == []


def test_collect_via_mcp_returns_empty_on_client_failure(tmp_path) -> None:
    class FailingClient:
        def call_tool(self, tool: str, arguments: dict):
            del tool, arguments
            raise RuntimeError("boom")

    producer = _DummyProducer(_ctx(tmp_path))
    producer._mcp_client = FailingClient()

    assert producer._collect_via_mcp() == []


def test_publish_to_mcp_stub_never_raises(tmp_path) -> None:
    producer = _DummyProducer(_ctx(tmp_path))

    producer._publish_to_mcp([])


def test_financial_datasets_collect_returns_empty_without_api_key(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("FINANCIAL_DATASETS_API_KEY", raising=False)
    producer = FinancialDatasetsMCPProducer(_ctx(tmp_path))

    assert producer.collect() == []


def test_financial_datasets_normalize_earnings_row(tmp_path) -> None:
    producer = FinancialDatasetsMCPProducer(_ctx(tmp_path))

    events = producer.normalize(
        [
            {
                "ticker": "NVDA",
                "actual_eps": 2.20,
                "estimated_eps": 2.00,
                "report_period": "2025-12-31",
            }
        ]
    )

    assert len(events) == 1
    ev = events[0]
    assert ev.type == EventType.SIGNAL_TRADFI_V1
    assert ev.payload["ticker"] == "NVDA"
    assert ev.payload["signal"] == "earnings_beat"
    assert ev.payload["producer"] == "financial_datasets"
    assert 0.0 <= ev.payload["confidence"] <= 1.0
