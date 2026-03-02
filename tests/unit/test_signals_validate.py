"""Tests for signal validation endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


class TestValidateEndpoint:
    def test_valid_ta_signal(self, client):
        resp = client.post(
            "/api/v1/signals/validate",
            json={"event_type": "signal.ta.v1", "payload": {"symbol": "BTC", "rsi_14": 55.0}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["errors"] == []

    def test_unknown_event_type(self, client):
        resp = client.post(
            "/api/v1/signals/validate",
            json={"event_type": "signal.nonexistent.v1", "payload": {}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert len(data["errors"]) > 0

    def test_missing_required_field(self, client):
        resp = client.post(
            "/api/v1/signals/validate",
            json={"event_type": "signal.ta.v1", "payload": {}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert any("symbol" in e for e in data["errors"])

    def test_valid_tradfi_signal(self, client):
        resp = client.post(
            "/api/v1/signals/validate",
            json={
                "event_type": "signal.tradfi.v1",
                "payload": {"symbol": "BTC", "basis_annualized": 5.2},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    def test_no_schema_registered(self, client):
        resp = client.post(
            "/api/v1/signals/validate",
            json={"event_type": "system.audit.v1", "payload": {}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert "No schema" in data["errors"][0]
