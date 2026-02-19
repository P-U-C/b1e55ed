from __future__ import annotations

import pytest

from api.main import create_app
from engine import __version__
from engine.core.database import Database
from tests.unit._api_test_client import make_client


@pytest.mark.anyio
async def test_health_returns_version(temp_dir, test_config):
    app = create_app()
    app.state.config = test_config
    app.state.db = Database(temp_dir / "brain.db")

    async with make_client(app) as ac:
        r = await ac.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["version"] == __version__
        assert "uptime_seconds" in data

    app.state.db.close()
