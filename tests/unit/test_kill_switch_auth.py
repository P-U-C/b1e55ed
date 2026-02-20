from __future__ import annotations

import pytest

from api.main import create_app
from engine.core.database import Database
from tests.unit._api_test_client import make_client


@pytest.mark.anyio
async def test_kill_switch_requires_separate_token(temp_dir, test_config):
    # configure both tokens
    test_config = test_config.model_copy(
        update={
            "api": test_config.api.model_copy(
                update={
                    "auth_token": "general",
                    "kill_switch_token": "ks",
                }
            )
        }
    )

    app = create_app()
    app.state.config = test_config
    app.state.db = Database(temp_dir / "brain.db")

    async with make_client(app) as ac:
        # general token can access brain status
        r = await ac.get("/api/v1/brain/status", headers={"Authorization": "Bearer general"})
        assert r.status_code == 200

        # but cannot set kill switch
        r2 = await ac.post(
            "/api/v1/kill-switch/set",
            headers={"Authorization": "Bearer general"},
            json={"level": 1, "reason": "test"},
        )
        assert r2.status_code == 401

        # kill switch token works
        r3 = await ac.post(
            "/api/v1/kill-switch/set",
            headers={"Authorization": "Bearer ks"},
            json={"level": 1, "reason": "test"},
        )
        assert r3.status_code == 200

    app.state.db.close()


@pytest.mark.anyio
async def test_kill_switch_missing_token_is_500(temp_dir, test_config):
    test_config = test_config.model_copy(update={"api": test_config.api.model_copy(update={"auth_token": "general"})})

    app = create_app()
    app.state.config = test_config
    app.state.db = Database(temp_dir / "brain.db")

    async with make_client(app) as ac:
        r = await ac.post(
            "/api/v1/kill-switch/set",
            headers={"Authorization": "Bearer general"},
            json={"level": 1, "reason": "test"},
        )
        assert r.status_code == 500
        assert r.json()["error"]["code"] == "auth.kill_switch_token_missing"

    app.state.db.close()
