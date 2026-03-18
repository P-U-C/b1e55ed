"""tests.unit.test_mcp_server

Tests for the MCP JSON-RPC 2.0 server at POST /mcp.
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest

from api.main import create_app
from engine.core.database import Database
from engine.mcp.registry import MCPProducerRegistry
from engine.mcp.server import MCPServer
from engine.mcp.types import MCPProducerManifest, MCPSignalPayload
from engine.producers.base import BaseProducer
from tests.unit._api_test_client import make_client

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rpc(method: str, params: dict | None = None, rpc_id: int = 1) -> dict:
    body: dict = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def _app_and_db(temp_dir, test_config):
    test_config = test_config.model_copy(update={"api": test_config.api.model_copy(update={"auth_token": "testkey"})})
    db = Database(temp_dir / "brain.db")
    app = create_app()
    app.state.config = test_config
    app.state.db = db
    yield app, db
    db.close()


_HEADERS = {"X-API-Key": "testkey"}
_BEARER = {"Authorization": "Bearer testkey"}


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_mcp_auth_missing(_app_and_db):
    """initialize and tools/list are public (no auth); tools/call requires auth."""
    app, _ = _app_and_db
    async with make_client(app) as ac:
        r = await ac.post("/mcp", json=_make_rpc("initialize"))
    assert r.status_code == 200  # initialize is public


@pytest.mark.anyio
async def test_mcp_auth_bearer(_app_and_db):
    app, _ = _app_and_db
    async with make_client(app) as ac:
        r = await ac.post("/mcp", json=_make_rpc("initialize"), headers=_BEARER)
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# initialize
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_mcp_initialize(_app_and_db):
    app, _ = _app_and_db
    async with make_client(app) as ac:
        r = await ac.post("/mcp", json=_make_rpc("initialize"), headers=_HEADERS)

    assert r.status_code == 200
    body = r.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 1
    result = body["result"]
    assert result["protocolVersion"] == "2024-11-05"
    assert "tools" in result["capabilities"]
    assert result["serverInfo"]["name"] == "b1e55ed"


# ---------------------------------------------------------------------------
# tools/list
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_mcp_tools_list(_app_and_db):
    app, _ = _app_and_db
    async with make_client(app) as ac:
        r = await ac.post("/mcp", json=_make_rpc("tools/list"), headers=_HEADERS)

    assert r.status_code == 200
    body = r.json()
    tools = body["result"]["tools"]
    assert isinstance(tools, list)
    tool_names = {t["name"] for t in tools}
    assert "get_brain_status" in tool_names
    assert "get_recent_signals" in tool_names
    assert "get_open_positions" in tool_names
    assert "get_signal_attribution" in tool_names
    assert "emit_producer_signal" in tool_names

    # Each tool has name, description, inputSchema
    for t in tools:
        assert "name" in t
        assert "description" in t
        assert "inputSchema" in t


# ---------------------------------------------------------------------------
# tools/call — get_brain_status
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_mcp_tool_get_brain_status(_app_and_db):
    app, _ = _app_and_db
    async with make_client(app) as ac:
        r = await ac.post(
            "/mcp",
            json=_make_rpc("tools/call", {"name": "get_brain_status", "arguments": {}}),
            headers=_HEADERS,
        )

    assert r.status_code == 200
    body = r.json()
    assert "result" in body
    result = body["result"]
    assert result["isError"] is False
    content_text = result["content"][0]["text"]
    data = json.loads(content_text)
    assert "regime" in data
    assert "kill_switch_level" in data


# ---------------------------------------------------------------------------
# tools/call — get_recent_signals
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_mcp_tool_get_recent_signals_empty(_app_and_db):
    app, _ = _app_and_db
    async with make_client(app) as ac:
        r = await ac.post(
            "/mcp",
            json=_make_rpc("tools/call", {"name": "get_recent_signals", "arguments": {"limit": 5}}),
            headers=_HEADERS,
        )

    assert r.status_code == 200
    body = r.json()
    data = json.loads(body["result"]["content"][0]["text"])
    assert isinstance(data, list)


@pytest.mark.anyio
async def test_mcp_tool_get_recent_signals_with_data(_app_and_db):
    app, db = _app_and_db

    # Insert a signal event
    db.append_event(
        event_type="signal.ta.v1",
        payload={"symbol": "BTC", "rsi_14": 45.0},
        source="test_producer",
    )

    async with make_client(app) as ac:
        r = await ac.post(
            "/mcp",
            json=_make_rpc("tools/call", {"name": "get_recent_signals", "arguments": {"limit": 10}}),
            headers=_HEADERS,
        )

    body = r.json()
    data = json.loads(body["result"]["content"][0]["text"])
    assert len(data) >= 1
    assert data[0]["type"] == "signal.ta.v1"


@pytest.mark.anyio
async def test_mcp_tool_get_recent_signals_domain_filter(_app_and_db):
    app, db = _app_and_db

    db.append_event(
        event_type="signal.ta.v1",
        payload={"symbol": "ETH"},
        source="ta_producer",
    )
    db.append_event(
        event_type="signal.onchain.v1",
        payload={"symbol": "BTC"},
        source="onchain_producer",
    )

    async with make_client(app) as ac:
        r = await ac.post(
            "/mcp",
            json=_make_rpc(
                "tools/call",
                {"name": "get_recent_signals", "arguments": {"limit": 10, "domain": "signal.ta"}},
            ),
            headers=_HEADERS,
        )

    body = r.json()
    data = json.loads(body["result"]["content"][0]["text"])
    assert all(d["type"].startswith("signal.ta") for d in data)


# ---------------------------------------------------------------------------
# tools/call — get_open_positions (mocked DB)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_mcp_tool_get_open_positions(_app_and_db):
    app, db = _app_and_db

    # Insert a position
    with db.conn:
        db.conn.execute(
            """
            INSERT INTO positions (id, platform, asset, direction, entry_price, size_notional,
                                   leverage, opened_at, status)
            VALUES ('pos-1', 'paper', 'BTC', 'long', 50000.0, 1000.0, 1.0, '2024-01-01T00:00:00', 'open')
            """
        )

    async with make_client(app) as ac:
        r = await ac.post(
            "/mcp",
            json=_make_rpc("tools/call", {"name": "get_open_positions", "arguments": {}}),
            headers=_HEADERS,
        )

    body = r.json()
    data = json.loads(body["result"]["content"][0]["text"])
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["asset"] == "BTC"
    assert data[0]["status"] == "open"


# ---------------------------------------------------------------------------
# tools/call — get_signal_attribution
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_mcp_tool_get_signal_attribution_not_found(_app_and_db):
    app, _ = _app_and_db
    async with make_client(app) as ac:
        r = await ac.post(
            "/mcp",
            json=_make_rpc(
                "tools/call",
                {"name": "get_signal_attribution", "arguments": {"signal_id": "nonexistent"}},
            ),
            headers=_HEADERS,
        )

    body = r.json()
    data = json.loads(body["result"]["content"][0]["text"])
    assert data["error"] == "signal_not_found"


@pytest.mark.anyio
async def test_mcp_tool_get_signal_attribution_found(_app_and_db):
    app, db = _app_and_db

    event = db.append_event(
        event_type="signal.ta.v1",
        payload={"symbol": "SOL"},
        source="ta_src",
    )
    event_id = event.id

    async with make_client(app) as ac:
        r = await ac.post(
            "/mcp",
            json=_make_rpc(
                "tools/call",
                {"name": "get_signal_attribution", "arguments": {"signal_id": event_id}},
            ),
            headers=_HEADERS,
        )

    body = r.json()
    data = json.loads(body["result"]["content"][0]["text"])
    assert data["signal_id"] == event_id
    assert data["type"] == "signal.ta.v1"
    assert data["source"] == "ta_src"


# ---------------------------------------------------------------------------
# tools/call — emit_producer_signal
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_mcp_tool_emit_producer_signal(_app_and_db):
    app, db = _app_and_db
    async with make_client(app) as ac:
        r = await ac.post(
            "/mcp",
            json=_make_rpc(
                "tools/call",
                {
                    "name": "emit_producer_signal",
                    "arguments": {
                        "producer_id": "test_producer",
                        "signal_type": "signal.ta.v1",
                        "payload": {"symbol": "BTC", "rsi_14": 60.0},
                    },
                },
            ),
            headers=_HEADERS,
        )

    body = r.json()
    assert body["result"]["isError"] is False
    data = json.loads(body["result"]["content"][0]["text"])
    assert "event_id" in data
    assert data["producer_id"] == "test_producer"
    assert data["signal_type"] == "signal.ta.v1"


@pytest.mark.anyio
async def test_mcp_tool_emit_producer_signal_invalid_type(_app_and_db):
    app, _ = _app_and_db
    async with make_client(app) as ac:
        r = await ac.post(
            "/mcp",
            json=_make_rpc(
                "tools/call",
                {
                    "name": "emit_producer_signal",
                    "arguments": {
                        "producer_id": "p",
                        "signal_type": "brain.cycle.v1",  # not a signal.*
                        "payload": {},
                    },
                },
            ),
            headers=_HEADERS,
        )

    body = r.json()
    assert "error" in body
    assert body["error"]["code"] == -32602  # INVALID_PARAMS


# ---------------------------------------------------------------------------
# Unknown method
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_mcp_unknown_method(_app_and_db):
    app, _ = _app_and_db
    async with make_client(app) as ac:
        r = await ac.post("/mcp", json=_make_rpc("nonexistent/method"), headers=_HEADERS)

    body = r.json()
    assert "error" in body
    assert body["error"]["code"] == -32601  # METHOD_NOT_FOUND


# ---------------------------------------------------------------------------
# Unknown tool name in tools/call
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_mcp_unknown_tool(_app_and_db):
    app, _ = _app_and_db
    async with make_client(app) as ac:
        r = await ac.post(
            "/mcp",
            json=_make_rpc("tools/call", {"name": "does_not_exist", "arguments": {}}),
            headers=_HEADERS,
        )

    body = r.json()
    assert "error" in body
    assert body["error"]["code"] == -32601


# ---------------------------------------------------------------------------
# Invalid JSON-RPC version
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_mcp_invalid_jsonrpc_version(_app_and_db):
    app, _ = _app_and_db
    async with make_client(app) as ac:
        r = await ac.post(
            "/mcp",
            json={"jsonrpc": "1.0", "id": 1, "method": "initialize"},
            headers=_HEADERS,
        )

    body = r.json()
    assert "error" in body
    assert body["error"]["code"] == -32600  # INVALID_REQUEST


# ---------------------------------------------------------------------------
# Outbound MCP registry + server (S2)
# ---------------------------------------------------------------------------


def _manifest(name: str = "demo", domain: str = "tradfi") -> MCPProducerManifest:
    return MCPProducerManifest(
        name=name,
        domain=domain,
        mcp_source_url=None,
        description=f"{name} producer",
        assets=[],
        schedule="* * * * *",
        registered_at="2026-03-01T00:00:00+00:00",
    )


def _signal(producer: str, i: int) -> MCPSignalPayload:
    return MCPSignalPayload(
        producer=producer,
        domain="tradfi",
        asset="BTC",
        direction="long",
        confidence=0.5,
        horizon="1h",
        reason=f"reason-{i}",
        timestamp=f"2026-03-01T00:00:{i:02d}+00:00",
        raw_score=float(i),
        metadata={"i": i},
    )


def test_registry_register():
    registry = MCPProducerRegistry()
    registry.register(_manifest("alpha"))

    producers = registry.list_producers()
    assert len(producers) == 1
    assert producers[0].name == "alpha"


def test_registry_push_signal():
    registry = MCPProducerRegistry()
    registry.register(_manifest("alpha"))
    registry.push_signal(_signal("alpha", 1))

    latest = registry.get_latest("alpha")
    assert latest is not None
    assert latest.reason == "reason-1"


def test_registry_ring_buffer():
    registry = MCPProducerRegistry()
    registry.register(_manifest("alpha"))

    for i in range(110):
        registry.push_signal(_signal("alpha", i))

    recent = registry.get_recent("alpha", n=200)
    assert len(recent) == 100
    assert recent[0].reason == "reason-10"
    assert recent[-1].reason == "reason-109"


def test_registry_get_recent():
    registry = MCPProducerRegistry()
    registry.register(_manifest("alpha"))

    for i in range(7):
        registry.push_signal(_signal("alpha", i))

    recent = registry.get_recent("alpha", n=3)
    assert [s.reason for s in recent] == ["reason-4", "reason-5", "reason-6"]


def test_registry_stats():
    registry = MCPProducerRegistry()
    registry.register(_manifest("alpha"))
    registry.register(_manifest("beta", domain="technical"))
    registry.push_signal(_signal("alpha", 1))

    stats = registry.stats()
    assert stats["producer_count"] == 2
    assert stats["total_signals_buffered"] == 1


def test_registry_thread_safety():
    registry = MCPProducerRegistry()
    registry.register(_manifest("alpha"))

    errors: list[Exception] = []

    def _worker(tid: int) -> None:
        try:
            for idx in range(100):
                registry.push_signal(_signal("alpha", tid * 100 + idx))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(tid,)) for tid in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    recent = registry.get_recent("alpha", n=200)
    assert len(recent) == 100
    assert all(signal.producer == "alpha" for signal in recent)


def test_server_tool_list_producers():
    registry = MCPProducerRegistry()
    registry.register(_manifest("alpha"))
    registry.register(_manifest("beta"))

    server = MCPServer(enabled=False)
    server._registry = registry

    producers = server.tool_list_producers()
    assert [p["name"] for p in producers] == ["alpha", "beta"]


def test_server_tool_get_latest():
    registry = MCPProducerRegistry()
    registry.register(_manifest("alpha"))

    server = MCPServer(enabled=False)
    server._registry = registry

    assert server.tool_get_latest_signal("alpha") is None

    registry.push_signal(_signal("alpha", 42))
    latest = server.tool_get_latest_signal("alpha")
    assert latest is not None
    assert latest["reason"] == "reason-42"


def test_server_not_running_by_default():
    server = MCPServer(enabled=False)
    assert server.is_running() is False


def test_base_producer_registers_on_init(monkeypatch):
    import engine.mcp.registry as registry_module

    monkeypatch.setattr(registry_module, "_REGISTRY", None)

    class MockProducer(BaseProducer):
        name = "mock_producer"
        domain = "technical"
        schedule = "continuous"
        assets = ["BTC"]

        def collect(self) -> list[dict]:
            return []

        def normalize(self, raw: list[dict]):
            return []

    _ = MockProducer(SimpleNamespace())

    names = [manifest.name for manifest in registry_module.get_registry().list_producers()]
    assert "mock_producer" in names
