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
