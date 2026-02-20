from __future__ import annotations

import pytest

from api.main import create_app
from engine.core.database import Database
from tests.unit._api_test_client import make_client


@pytest.mark.anyio
async def test_producer_register_list_remove_lifecycle(temp_dir, test_config):
    app = create_app()
    app.state.config = test_config
    app.state.db = Database(temp_dir / "brain.db")

    async with make_client(app) as ac:
        reg = {
            "name": "unit-test-producer",
            "domain": "technical",
            "endpoint": "https://example.com/signals",
            "schedule": "*/5 * * * *",
        }

        r1 = await ac.post("/api/v1/producers/register", json=reg)
        assert r1.status_code == 200
        js1 = r1.json()
        assert js1["name"] == reg["name"]
        assert js1["endpoint"] == reg["endpoint"]
        assert "registered_at" in js1

        r2 = await ac.get("/api/v1/producers/")
        assert r2.status_code == 200
        js2 = r2.json()
        assert "producers" in js2
        assert any(p["name"] == reg["name"] for p in js2["producers"])

        r3 = await ac.delete(f"/api/v1/producers/{reg['name']}")
        assert r3.status_code == 200
        assert r3.json()["removed"] == reg["name"]

        r4 = await ac.get("/api/v1/producers/")
        assert r4.status_code == 200
        assert all(p["name"] != reg["name"] for p in r4.json()["producers"])

    app.state.db.close()


@pytest.mark.anyio
async def test_duplicate_registration_returns_structured_error(temp_dir, test_config):
    app = create_app()
    app.state.config = test_config
    app.state.db = Database(temp_dir / "brain.db")

    async with make_client(app) as ac:
        reg = {
            "name": "dup-producer",
            "domain": "sentiment",
            "endpoint": "https://example.com/x",
            "schedule": "*/15 * * * *",
        }

        r1 = await ac.post("/api/v1/producers/register", json=reg)
        assert r1.status_code == 200

        r2 = await ac.post("/api/v1/producers/register", json=reg)
        assert r2.status_code == 409
        js = r2.json()
        assert js["error"]["code"] == "producer.duplicate"
        assert js["error"]["name"] == "dup-producer"

    app.state.db.close()
