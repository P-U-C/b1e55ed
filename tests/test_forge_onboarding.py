from __future__ import annotations

import pytest

from api.main import create_app
from engine.core.database import Database
from tests.unit._api_test_client import make_client


def _make_app(temp_dir, test_config):
    test_config = test_config.model_copy(update={"api": test_config.api.model_copy(update={"auth_token": "secret"})})
    db = Database(temp_dir / "brain.db")
    app = create_app()
    app.state.config = test_config
    app.state.db = db
    return app, db


@pytest.mark.anyio
async def test_forge_estimate_fast_machine(temp_dir, test_config):
    """Fast machine (8 cores, Rust) should get forge_now recommendation."""
    app, db = _make_app(temp_dir, test_config)

    async with make_client(app) as client:
        resp = await client.post(
            "/api/v1/spi/producers/test-agent/forge-estimate",
            json={"cpu_cores": 8, "has_rust": True, "platform": "linux"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["recommendation"] == "forge_now"
    assert data["estimated_seconds"] < 60

    db.close()


@pytest.mark.anyio
async def test_forge_estimate_slow_machine(temp_dir, test_config):
    """Slow machine (2 cores, no Rust) should get forge_later recommendation."""
    app, db = _make_app(temp_dir, test_config)

    async with make_client(app) as client:
        resp = await client.post(
            "/api/v1/spi/producers/test-agent/forge-estimate",
            json={"cpu_cores": 2, "has_rust": False, "platform": "linux"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["recommendation"] == "forge_later"
    assert data["estimated_seconds"] > 600

    db.close()


@pytest.mark.anyio
async def test_forge_complete_invalid_prefix(temp_dir, test_config):
    """Address not starting with 0xb1e55ed should be rejected."""
    app, db = _make_app(temp_dir, test_config)

    async with make_client(app) as client:
        resp = await client.post(
            "/api/v1/spi/producers/test-agent/forge-complete",
            json={"forged_address": "0xdeadbeef1234567890", "signature": "0x0000"},
        )

    assert resp.status_code == 400

    db.close()


@pytest.mark.anyio
async def test_forge_info_in_registration(temp_dir, test_config):
    """Registration response should include forge info."""
    app, db = _make_app(temp_dir, test_config)

    async with make_client(app) as client:
        resp = await client.post(
            "/api/v1/spi/producers",
            json={
                "producer_id": "forge-test-agent",
                "producer_name": "Forge Test",
            },
        )

    assert resp.status_code == 201
    data = resp.json()
    assert "forge" in data
    assert data["forge"]["required"] is False
    assert data["forge"]["grace_period_days"] == 90
    assert data["forge"]["estimate_url"] == "/api/v1/spi/producers/forge-test-agent/forge-estimate"

    db.close()
