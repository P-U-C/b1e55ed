from __future__ import annotations

import pytest
from api.main import create_app
from engine.core.database import Database
from tests.unit._api_test_client import make_client


@pytest.mark.anyio
async def test_brain_status_and_run(temp_dir, test_config, monkeypatch):
    # set auth token
    test_config = test_config.model_copy(update={"api": test_config.api.model_copy(update={"auth_token": "secret"})})

    app = create_app()
    app.state.config = test_config
    app.state.db = Database(temp_dir / "brain.db")

    headers = {"Authorization": "Bearer secret"}

    async with make_client(app) as ac:
        r = await ac.get("/brain/status", headers=headers)
        assert r.status_code == 200
        js = r.json()
        assert "kill_switch_level" in js

        r2 = await ac.post("/brain/run", headers=headers)
        assert r2.status_code == 200
        js2 = r2.json()
        assert js2["cycle_id"]

        # After run, status should have last_cycle_id
        r3 = await ac.get("/brain/status", headers=headers)
        assert r3.status_code == 200
        js3 = r3.json()
        assert js3["last_cycle_id"] == js2["cycle_id"]

    app.state.db.close()
