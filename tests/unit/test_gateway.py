"""Unit tests for the b1e55ed MCP Gateway."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

# Patch config before importing app
_TEST_CONFIG = {
    "b1e55ed_url": "http://localhost:5050",
    "b1e55ed_token": "",
    "port": 7338,
    "users": [
        {"api_key": "test-analyst", "name": "analyst1", "role": "analyst"},
        {"api_key": "test-pm", "name": "pm1", "role": "pm"},
        {"api_key": "test-admin", "name": "admin1", "role": "admin"},
    ],
}


@pytest.fixture(autouse=True)
def _patch_config(tmp_path, monkeypatch):
    """Write a temp config and point the gateway at it."""
    import yaml

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(_TEST_CONFIG))
    monkeypatch.setenv("GATEWAY_CONFIG", str(cfg_path))

    # Re-import with patched config
    import gateway.main as gw

    gw._CONFIG_PATH = str(cfg_path)
    new_cfg = gw._load_config()
    gw.CFG = new_cfg
    gw.B1E55ED_URL = new_cfg["b1e55ed_url"].rstrip("/")
    gw.B1E55ED_TOKEN = new_cfg.get("b1e55ed_token", "")
    gw.USERS = {}
    for u in new_cfg.get("users", []):
        gw.USERS[u["api_key"]] = {"name": u["name"], "role": u["role"]}
    gw.DATA_DIR = tmp_path / "data"
    gw.DATA_DIR.mkdir(exist_ok=True)
    gw.PENDING_PATH = gw.DATA_DIR / "pending_signals.jsonl"
    gw.AUDIT_PATH = gw.DATA_DIR / "audit.jsonl"


@pytest.fixture
def client():
    from gateway.main import app

    return TestClient(app)


def _mcp_body(tool: str, args: dict | None = None) -> dict:
    return {
        "method": "tools/call",
        "params": {"name": tool, "arguments": args or {}},
        "id": 1,
        "jsonrpc": "2.0",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_health_returns_200(client):
    """GET /health always returns 200 even if upstream is down."""
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["gateway"] == "ok"


def test_unknown_key_returns_401(client):
    """Requests with invalid API keys are rejected."""
    resp = client.post(
        "/mcp/call",
        json=_mcp_body("get_brain_status"),
        headers={"X-API-Key": "bad-key"},
    )
    assert resp.status_code == 401


def test_analyst_blocked_from_submit_research_signal(client):
    """Analyst role cannot call submit_research_signal (admin-only tool)."""
    resp = client.post(
        "/mcp/call",
        json=_mcp_body("submit_research_signal", {"signal": "test"}),
        headers={"X-API-Key": "test-analyst"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "error" in body
    assert "cannot call" in body["error"]["message"]


def test_pm_signal_queued_not_forwarded(client):
    """PM calling submit_research_signal is queued for admin approval, not forwarded."""
    resp = client.post(
        "/mcp/call",
        json=_mcp_body("submit_research_signal", {"signal": "alpha"}),
        headers={"X-API-Key": "test-pm"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # PM role has submit_research_signal but calls are queued, not forwarded directly
    assert "result" in body
    assert body["result"]["queued"] is True
    assert "signal_id" in body["result"]


def test_audit_log_written(client, tmp_path):
    """Successful and denied calls both produce audit entries."""
    from gateway.main import AUDIT_PATH

    # Make a denied call
    client.post(
        "/mcp/call",
        json=_mcp_body("submit_research_signal"),
        headers={"X-API-Key": "test-analyst"},
    )

    assert AUDIT_PATH.exists()
    lines = AUDIT_PATH.read_text().strip().splitlines()
    assert len(lines) >= 1
    entry = json.loads(lines[0])
    assert entry["user"] == "analyst1"
    assert entry["status"] == "denied"


@patch("gateway.main._proxy_to_b1e55ed", new_callable=AsyncMock)
def test_analyst_allowed_tools_proxied(mock_proxy, client):
    """Analyst can call tools in their role — request is proxied upstream."""
    mock_proxy.return_value = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"regime": "risk-on"},
    }
    resp = client.post(
        "/mcp/call",
        json=_mcp_body("get_regime_status"),
        headers={"X-API-Key": "test-analyst"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "result" in body
    mock_proxy.assert_called_once()
