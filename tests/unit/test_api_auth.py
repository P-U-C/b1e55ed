from __future__ import annotations

import pytest

from api.main import create_app
from engine.core.database import Database
from tests.unit._api_test_client import make_client


@pytest.mark.anyio
async def test_protected_routes_require_auth(temp_dir, test_config):
    app = create_app()
    test_config = test_config.model_copy(update={"api": test_config.api.model_copy(update={"auth_token": "secret"})})
    app.state.config = test_config
    app.state.db = Database(temp_dir / "brain.db")

    async with make_client(app) as ac:
        r = await ac.get("/signals")
        assert r.status_code == 401

        r2 = await ac.get("/health")
        assert r2.status_code == 200

    app.state.db.close()
