from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import engine.mcp.registry as registry_module
from api.main import create_app
from engine.core.database import Database
from engine.mcp.auth import validate_mcp_key
from engine.mcp.registry import MCPProducerRegistry, get_registry
from engine.mcp.types import MCPProducerManifest, MCPSignalPayload


@pytest.fixture(autouse=True)
def fresh_registry(monkeypatch: pytest.MonkeyPatch) -> MCPProducerRegistry:
    registry = MCPProducerRegistry()
    monkeypatch.setattr(registry_module, "_REGISTRY", registry)
    return registry


@pytest.fixture()
def client(temp_dir, test_config):
    app = create_app()
    db = Database(temp_dir / "brain.db")
    app.state.config = test_config
    app.state.db = db

    with TestClient(app) as test_client:
        yield test_client

    db.close()


def _manifest(name: str) -> MCPProducerManifest:
    return MCPProducerManifest(
        name=name,
        domain="technical",
        mcp_source_url=None,
        description=f"{name} producer",
        assets=["BTC"],
        schedule="*/5 * * * *",
        registered_at="2026-03-01T00:00:00+00:00",
    )


def _signal(producer: str) -> MCPSignalPayload:
    return MCPSignalPayload(
        producer=producer,
        domain="technical",
        asset="BTC",
        direction="long",
        confidence=0.9,
        horizon="4h",
        reason="test",
        timestamp="2026-03-01T00:01:00+00:00",
        raw_score=9.0,
        metadata={"source": "test"},
    )


def test_mcp_producers_empty(client: TestClient) -> None:
    response = client.get("/api/v1/mcp/producers")

    assert response.status_code == 200
    assert response.json() == {"producers": [], "count": 0}


def test_mcp_producers_with_data(client: TestClient) -> None:
    registry = get_registry()
    registry.register(_manifest("alpha"))
    registry.push_signal(_signal("alpha"))

    response = client.get("/api/v1/mcp/producers")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["producers"][0]["name"] == "alpha"
    assert body["producers"][0]["latest_signal"]["producer"] == "alpha"


def test_mcp_status_ok(client: TestClient) -> None:
    response = client.get("/api/v1/mcp/status")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["registry_ok"] is True


def test_mcp_status_producer_count(client: TestClient) -> None:
    registry = get_registry()
    registry.register(_manifest("alpha"))
    registry.register(_manifest("beta"))

    response = client.get("/api/v1/mcp/status")

    assert response.status_code == 200
    body = response.json()
    assert body["producer_count"] == 2


def test_validate_mcp_key_valid() -> None:
    assert validate_mcp_key("abc", ["abc", "xyz"]) is True


def test_validate_mcp_key_invalid() -> None:
    assert validate_mcp_key("bad", ["abc"]) is False


# ---------------------------------------------------------------------------
# ERC-8004: Public MCP methods + well-known manifest
# ---------------------------------------------------------------------------


def _rpc(method: str, params: dict | None = None, rpc_id: int = 1) -> dict:
    body: dict = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


@pytest.fixture()
def authed_client(temp_dir, test_config):
    """Client with auth_token configured — non-public methods require auth."""
    app = create_app()
    db = Database(temp_dir / "brain.db")
    cfg = test_config.model_copy(
        update={"api": test_config.api.model_copy(update={"auth_token": "test-secret"})},
    )
    app.state.config = cfg
    app.state.db = db

    with TestClient(app) as tc:
        yield tc

    db.close()


class TestMCPPublicMethods:
    """initialize and tools/list must work WITHOUT auth."""

    def test_initialize_no_auth(self, authed_client: TestClient) -> None:
        resp = authed_client.post("/mcp", json=_rpc("initialize"))
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        assert "protocolVersion" in data["result"]

    def test_tools_list_no_auth(self, authed_client: TestClient) -> None:
        resp = authed_client.post("/mcp", json=_rpc("tools/list"))
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        assert "tools" in data["result"]
        assert isinstance(data["result"]["tools"], list)

        tool_names = {tool["name"] for tool in data["result"]["tools"]}
        assert {
            "get_brain_status",
            "get_recent_signals",
            "get_open_positions",
            "get_signal_attribution",
            "b1e55ed_provenance_check",
            "emit_producer_signal",
            "get_regime_status",
            "get_top_signals",
            "get_regime_history",
            "submit_research_signal",
            "get_signals_bulk_export",
        }.issubset(tool_names)

    def test_tools_call_requires_auth(self, authed_client: TestClient) -> None:
        resp = authed_client.post(
            "/mcp",
            json=_rpc("tools/call", {"name": "get_brain_status", "arguments": {}}),
        )
        assert resp.status_code == 401


class TestWellKnownAgentRegistration:
    """/.well-known/agent-registration.json must return ERC-8004 manifest."""

    def test_returns_200(self, client: TestClient) -> None:
        resp = client.get("/.well-known/agent-registration.json")
        assert resp.status_code == 200

    def test_synthesis_participant(self, client: TestClient) -> None:
        data = client.get("/.well-known/agent-registration.json").json()
        assert data["synthesis_participant"] is True

    def test_has_required_fields(self, client: TestClient) -> None:
        data = client.get("/.well-known/agent-registration.json").json()
        assert data["name"] == "b1e55ed"
        assert "endpoints" in data
        assert "supportedTrust" in data
        assert "reputation" in data["supportedTrust"]
