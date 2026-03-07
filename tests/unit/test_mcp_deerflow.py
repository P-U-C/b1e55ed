"""Tests for DeerFlow MCP integration — S0 sprint."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from api.main import create_app
from engine.core.database import Database
from engine.core.events import (
    EventType,
    ResearchSignalPayload,
    SignalClass,
)
from engine.core.karma import (
    _DEFAULT_LLM_KARMA_CEILING,
    bump_karma_ceiling,
    ensure_producer_karma_config,
    frequency_penalty,
    karma_weight_for_signal,
)
from tests.unit._api_test_client import make_client


def _make_rpc(method, params=None, rpc_id=1):
    body = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


def _call_tool(tool_name, arguments=None):
    return _make_rpc("tools/call", {"name": tool_name, "arguments": arguments or {}})


@pytest.fixture()
def db_and_app(temp_dir, test_config):
    test_config = test_config.model_copy(update={"api": test_config.api.model_copy(update={"auth_token": "testkey"})})
    db = Database(temp_dir / "brain.db")
    app = create_app()
    app.state.config = test_config
    app.state.db = db
    yield db, app
    db.close()


_HEADERS = {"X-API-Key": "testkey"}


def _insert_regime_event(db, regime, ts=None):
    ts = ts or datetime.now(tz=UTC)
    db.append_event(event_type=EventType.REGIME_CHANGE_V1, payload={"regime": regime}, source="test", ts=ts)


def _insert_signal_event(db, symbol="BTC", domain="ta", source="test_producer", signal_class=None, ts=None):
    ts = ts or datetime.now(tz=UTC)
    etype_map = {"ta": EventType.SIGNAL_TA_V1, "onchain": EventType.SIGNAL_ONCHAIN_V1, "research": EventType.SIGNAL_RESEARCH_V1}
    etype = etype_map.get(domain, EventType.SIGNAL_TA_V1)
    payload = {"symbol": symbol}
    if domain == "ta":
        payload["trend"] = "bullish"
    elif domain == "research":
        payload.update(
            {
                "signal_class": signal_class or "observation",
                "confidence": 0.8,
                "direction": "bullish",
                "rationale": "test",
                "operator_node_id": "node-test",
            }
        )
    if signal_class and domain != "research":
        payload["signal_class"] = signal_class
    ev = db.append_event(event_type=etype, payload=payload, source=source, ts=ts)
    return ev.id


# --- get_regime_status ---


@pytest.mark.anyio
async def test_regime_status_empty(db_and_app):
    db, app = db_and_app
    async with make_client(app) as ac:
        r = await ac.post("/mcp", json=_call_tool("get_regime_status"), headers=_HEADERS)
    assert r.status_code == 200
    result = json.loads(r.json()["result"]["content"][0]["text"])
    assert result["regime"] is None
    assert result["regime_changed_at"] is None
    assert result["kill_switch_level"] == 0
    assert result["trend"] == "stable"
    assert result["last_cycle_at"] is None


@pytest.mark.anyio
async def test_regime_status_with_events(db_and_app):
    db, app = db_and_app
    now = datetime.now(tz=UTC)
    _insert_regime_event(db, "neutral", now - timedelta(hours=48))
    _insert_regime_event(db, "bull", now - timedelta(hours=1))
    async with make_client(app) as ac:
        r = await ac.post("/mcp", json=_call_tool("get_regime_status"), headers=_HEADERS)
    result = json.loads(r.json()["result"]["content"][0]["text"])
    assert result["regime"] == "bull"
    assert result["trend"] == "strengthening"


# --- get_top_signals ---


@pytest.mark.anyio
async def test_top_signals_paginated(db_and_app):
    db, app = db_and_app
    now = datetime.now(tz=UTC)
    for i in range(5):
        _insert_signal_event(db, symbol="BTC", domain="ta", ts=now - timedelta(minutes=i))
    async with make_client(app) as ac:
        r = await ac.post("/mcp", json=_call_tool("get_top_signals", {"limit": 3}), headers=_HEADERS)
    result = json.loads(r.json()["result"]["content"][0]["text"])
    assert result["total_returned"] == 3
    assert result["next_cursor"] is not None
    # paginate
    async with make_client(app) as ac:
        r2 = await ac.post("/mcp", json=_call_tool("get_top_signals", {"limit": 3, "cursor": result["next_cursor"]}), headers=_HEADERS)
    result2 = json.loads(r2.json()["result"]["content"][0]["text"])
    assert result2["total_returned"] == 2
    assert result2["next_cursor"] is None


@pytest.mark.anyio
async def test_top_signals_filters_by_domain(db_and_app):
    db, app = db_and_app
    _insert_signal_event(db, symbol="BTC", domain="ta")
    _insert_signal_event(db, symbol="ETH", domain="onchain")
    _insert_signal_event(db, symbol="SOL", domain="ta")
    async with make_client(app) as ac:
        r = await ac.post("/mcp", json=_call_tool("get_top_signals", {"domain": "ta"}), headers=_HEADERS)
    result = json.loads(r.json()["result"]["content"][0]["text"])
    assert result["total_returned"] == 2
    assert all("signal.ta" in item["type"] for item in result["items"])


@pytest.mark.anyio
async def test_top_signals_filters_by_signal_class(db_and_app):
    db, app = db_and_app
    _insert_signal_event(db, domain="research", signal_class="observation")
    _insert_signal_event(db, domain="research", signal_class="detection")
    _insert_signal_event(db, domain="research", signal_class="observation")
    async with make_client(app) as ac:
        r = await ac.post("/mcp", json=_call_tool("get_top_signals", {"signal_class": "observation"}), headers=_HEADERS)
    result = json.loads(r.json()["result"]["content"][0]["text"])
    assert result["total_returned"] == 2


# --- get_regime_history ---


@pytest.mark.anyio
async def test_regime_history_with_stability(db_and_app):
    db, app = db_and_app
    now = datetime.now(tz=UTC)
    for i, regime in enumerate(["neutral", "bull", "bear", "bull"]):
        _insert_regime_event(db, regime, now - timedelta(hours=24 * (3 - i)))
    async with make_client(app) as ac:
        r = await ac.post("/mcp", json=_call_tool("get_regime_history", {"days": 7}), headers=_HEADERS)
    result = json.loads(r.json()["result"]["content"][0]["text"])
    assert result["current_regime"] == "bull"
    assert result["regime_stability"] == "volatile"
    assert len(result["items"]) == 4


# --- submit_research_signal ---


@pytest.mark.anyio
async def test_submit_observation_signal(db_and_app):
    db, app = db_and_app
    async with make_client(app) as ac:
        r = await ac.post(
            "/mcp",
            json=_call_tool(
                "submit_research_signal",
                {
                    "symbol": "BTC",
                    "signal_class": "observation",
                    "confidence": 0.7,
                    "direction": "bullish",
                    "rationale": "Whale accumulation",
                    "operator_node_id": "node-abc",
                },
            ),
            headers=_HEADERS,
        )
    assert r.status_code == 200
    data = r.json()
    assert data["result"]["isError"] is False
    result = json.loads(data["result"]["content"][0]["text"])
    assert result["event_id"]
    assert result["signal_class"] == "observation"
    assert result["karma_ceiling_active"] is True


@pytest.mark.anyio
async def test_submit_conviction_with_horizon(db_and_app):
    db, app = db_and_app
    async with make_client(app) as ac:
        r = await ac.post(
            "/mcp",
            json=_call_tool(
                "submit_research_signal",
                {
                    "symbol": "ETH",
                    "signal_class": "conviction",
                    "confidence": 0.9,
                    "direction": "bullish",
                    "rationale": "Breakout",
                    "operator_node_id": "node-xyz",
                    "horizon": "1-7d",
                    "sources": ["https://example.com"],
                },
            ),
            headers=_HEADERS,
        )
    result = json.loads(r.json()["result"]["content"][0]["text"])
    assert result["signal_class"] == "conviction"


@pytest.mark.anyio
async def test_submit_conviction_without_horizon_fails(db_and_app):
    db, app = db_and_app
    async with make_client(app) as ac:
        r = await ac.post(
            "/mcp",
            json=_call_tool(
                "submit_research_signal",
                {
                    "symbol": "BTC",
                    "signal_class": "conviction",
                    "confidence": 0.8,
                    "direction": "bearish",
                    "rationale": "No horizon",
                    "operator_node_id": "node-123",
                },
            ),
            headers=_HEADERS,
        )
    data = r.json()
    assert "error" in data


@pytest.mark.anyio
async def test_submit_missing_operator_node_id_fails(db_and_app):
    db, app = db_and_app
    async with make_client(app) as ac:
        r = await ac.post(
            "/mcp",
            json=_call_tool(
                "submit_research_signal",
                {
                    "symbol": "BTC",
                    "signal_class": "observation",
                    "confidence": 0.5,
                    "direction": "neutral",
                    "rationale": "Missing node ID",
                },
            ),
            headers=_HEADERS,
        )
    data = r.json()
    assert "error" in data


# --- get_signals_bulk_export ---


@pytest.mark.anyio
async def test_bulk_export_with_time_range(db_and_app):
    db, app = db_and_app
    now = datetime.now(tz=UTC)
    for i in range(10):
        _insert_signal_event(db, symbol="BTC", domain="ta", ts=now - timedelta(hours=i))
    from_ts = (now - timedelta(hours=5)).isoformat()
    to_ts = now.isoformat()
    async with make_client(app) as ac:
        r = await ac.post(
            "/mcp",
            json=_call_tool(
                "get_signals_bulk_export",
                {
                    "from_ts": from_ts,
                    "to_ts": to_ts,
                    "limit": 100,
                },
            ),
            headers=_HEADERS,
        )
    result = json.loads(r.json()["result"]["content"][0]["text"])
    assert result["total_returned"] >= 1
    assert result["total_returned"] <= 10


# --- ResearchSignalPayload validation ---


def test_research_payload_conviction_without_horizon():
    with pytest.raises(ValueError, match="conviction requires horizon"):
        ResearchSignalPayload(
            symbol="BTC",
            signal_class=SignalClass.CONVICTION,
            confidence=0.9,
            direction="bullish",
            rationale="test",
            operator_node_id="node-1",
        )


def test_research_payload_observation_valid():
    p = ResearchSignalPayload(
        symbol="ETH",
        signal_class=SignalClass.OBSERVATION,
        confidence=0.6,
        direction="neutral",
        rationale="test",
        operator_node_id="node-2",
    )
    assert p.signal_class == SignalClass.OBSERVATION
    assert p.horizon is None


def test_research_payload_conviction_with_horizon():
    p = ResearchSignalPayload(
        symbol="SOL",
        signal_class=SignalClass.CONVICTION,
        confidence=0.85,
        direction="bullish",
        horizon="1-7d",
        rationale="breakout",
        operator_node_id="node-3",
    )
    assert p.horizon == "1-7d"


# --- frequency_penalty ---


def test_frequency_penalty_low():
    assert frequency_penalty(0.5) == 1.0
    assert frequency_penalty(1.0) == 1.0


def test_frequency_penalty_medium():
    assert frequency_penalty(3.0) == 0.7
    assert frequency_penalty(5.0) == 0.7


def test_frequency_penalty_high():
    assert frequency_penalty(10.0) == 0.4
    assert frequency_penalty(20.0) == 0.4


def test_frequency_penalty_extreme():
    assert frequency_penalty(50.0) == 0.1
    assert frequency_penalty(100.0) == 0.1


# --- karma weight + ceiling ---


def test_karma_weight_for_signal(temp_dir):
    db = Database(temp_dir / "test_karma.db")
    try:
        ensure_producer_karma_config(db, "deerflow:node-1", source_type="llm_research")
        weight = karma_weight_for_signal(db, "deerflow:node-1", "BTC")
        assert weight == pytest.approx(_DEFAULT_LLM_KARMA_CEILING, abs=0.01)
    finally:
        db.close()


def test_bump_karma_ceiling(temp_dir):
    db = Database(temp_dir / "test_ceiling.db")
    try:
        ensure_producer_karma_config(db, "deerflow:node-2", source_type="llm_research")
        new_ceiling = bump_karma_ceiling(db, "deerflow:node-2")
        assert new_ceiling == pytest.approx(0.4, abs=0.01)
        new_ceiling = bump_karma_ceiling(db, "deerflow:node-2")
        assert new_ceiling == pytest.approx(0.5, abs=0.01)
    finally:
        db.close()


def test_non_llm_producer_ceiling(temp_dir):
    db = Database(temp_dir / "test_ceiling2.db")
    try:
        ensure_producer_karma_config(db, "manual:operator", source_type="human")
        weight = karma_weight_for_signal(db, "manual:operator", "BTC")
        assert weight == pytest.approx(1.0, abs=0.01)
    finally:
        db.close()
