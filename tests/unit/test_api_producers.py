from __future__ import annotations

import pytest

from api.main import create_app
from engine.core.database import Database
from tests.unit._api_test_client import make_client


@pytest.mark.anyio
async def test_producers_status(temp_dir, test_config):
    test_config = test_config.model_copy(update={"api": test_config.api.model_copy(update={"auth_token": "secret"})})

    db = Database(temp_dir / "brain.db")

    app = create_app()
    app.state.config = test_config
    app.state.db = db

    headers = {"Authorization": "Bearer secret"}
    async with make_client(app) as ac:
        r = await ac.get("/producers/status", headers=headers)
        assert r.status_code == 200
        js = r.json()
        assert "producers" in js
        assert isinstance(js["producers"], dict)

    db.close()
