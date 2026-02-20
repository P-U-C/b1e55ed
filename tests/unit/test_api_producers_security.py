from __future__ import annotations

import pytest

from api.main import create_app
from engine.core.database import Database
from tests.unit._api_test_client import make_client


@pytest.mark.anyio
async def test_producer_register_blocks_ssrf(temp_dir, test_config):
    test_config = test_config.model_copy(update={"api": test_config.api.model_copy(update={"auth_token": "secret"})})

    app = create_app()
    app.state.config = test_config
    app.state.db = Database(temp_dir / "brain.db")

    headers = {"Authorization": "Bearer secret"}

    async with make_client(app) as ac:
        r = await ac.post(
            "/api/v1/producers/register",
            headers=headers,
            json={
                "name": "evil",
                "domain": "social",
                "endpoint": "http://127.0.0.1:1234/steal",
                "schedule": "*/15 * * * *",
            },
        )
        assert r.status_code == 400
        js = r.json()
        assert js["error"]["code"] == "producer.endpoint_blocked"

    app.state.db.close()
