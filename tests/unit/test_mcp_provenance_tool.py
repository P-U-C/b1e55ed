"""tests.unit.test_mcp_provenance_tool

Tests for the b1e55ed_provenance_check MCP tool.
"""

from __future__ import annotations

import json

import pytest

from api.main import create_app
from engine.core.database import Database
from engine.core.events import EventType
from tests.unit._api_test_client import make_client

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rpc(method: str, params: dict | None = None, rpc_id: int = 1) -> dict:
    body: dict = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


def _seed_events(db: Database, producer_id: str, count: int = 3) -> None:
    for _ in range(count):
        db.append_event(
            event_type=EventType.SIGNAL_CURATOR_V1,
            payload={
                "symbol": "ETH",
                "direction": "bullish",
                "conviction": 7.0,
                "rationale": "test",
                "source": producer_id,
            },
            source=producer_id,
        )


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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProvenanceToolInToolsList:
    @pytest.mark.anyio
    async def test_provenance_tool_in_tools_list(self, _app_and_db):
        app, _ = _app_and_db

        async with make_client(app) as ac:
            r = await ac.post("/mcp", json=_make_rpc("tools/list"), headers=_HEADERS)

        assert r.status_code == 200
        body = r.json()
        tools = body["result"]["tools"]
        tool_names = [t["name"] for t in tools]
        assert "b1e55ed_provenance_check" in tool_names

    @pytest.mark.anyio
    async def test_provenance_tool_has_correct_schema(self, _app_and_db):
        app, _ = _app_and_db

        async with make_client(app) as ac:
            r = await ac.post("/mcp", json=_make_rpc("tools/list"), headers=_HEADERS)

        assert r.status_code == 200
        tools = r.json()["result"]["tools"]
        tool = next((t for t in tools if t["name"] == "b1e55ed_provenance_check"), None)
        assert tool is not None
        schema = tool["inputSchema"]
        assert "producer_id" in schema["properties"]
        assert "producer_id" in schema["required"]
        # signal_type should be optional (not in required)
        assert "signal_type" in schema["properties"]
        assert "signal_type" not in schema.get("required", [])


class TestProvenanceToolCall:
    @pytest.mark.anyio
    async def test_provenance_tool_call_found(self, _app_and_db):
        app, db = _app_and_db
        pid = "mcp_test_producer"
        _seed_events(db, pid)

        payload = _make_rpc(
            "tools/call",
            params={"name": "b1e55ed_provenance_check", "arguments": {"producer_id": pid}},
        )
        async with make_client(app) as ac:
            r = await ac.post("/mcp", json=payload, headers=_HEADERS)

        assert r.status_code == 200
        body = r.json()
        assert "result" in body
        assert body["result"]["isError"] is False
        content = json.loads(body["result"]["content"][0]["text"])
        assert content["producer_id"] == pid
        assert content["has_provenance"] is True

    @pytest.mark.anyio
    async def test_provenance_tool_call_not_found(self, _app_and_db):
        app, db = _app_and_db
        pid = "mcp_unknown_producer"

        payload = _make_rpc(
            "tools/call",
            params={"name": "b1e55ed_provenance_check", "arguments": {"producer_id": pid}},
        )
        async with make_client(app) as ac:
            r = await ac.post("/mcp", json=payload, headers=_HEADERS)

        assert r.status_code == 200
        body = r.json()
        assert body["result"]["isError"] is False
        content = json.loads(body["result"]["content"][0]["text"])
        assert content["has_provenance"] is False


class TestProvenanceToolMissingProducerId:
    @pytest.mark.anyio
    async def test_provenance_tool_missing_producer_id(self, _app_and_db):
        app, _ = _app_and_db

        payload = _make_rpc(
            "tools/call",
            params={"name": "b1e55ed_provenance_check", "arguments": {}},
        )
        async with make_client(app) as ac:
            r = await ac.post("/mcp", json=payload, headers=_HEADERS)

        assert r.status_code == 200
        body = r.json()
        # Should return an error response (INVALID_PARAMS = -32602)
        assert "error" in body
        assert body["error"]["code"] == -32602
