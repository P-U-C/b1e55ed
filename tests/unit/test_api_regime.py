from __future__ import annotations

import pytest

from api.main import create_app
from engine.core.database import Database
from engine.core.events import EventType
from tests.unit._api_test_client import make_client


@pytest.mark.anyio
async def test_regime_returns_current(temp_dir, test_config):
    test_config = test_config.model_copy(update={"api": test_config.api.model_copy(update={"auth_token": "secret"})})

    db = Database(temp_dir / "brain.db")
    db.append_event(event_type=EventType.REGIME_CHANGE_V1, payload={"regime": "RISK_ON"})

    app = create_app()
    app.state.config = test_config
    app.state.db = db

    headers = {"Authorization": "Bearer secret"}
    async with make_client(app) as ac:
        r = await ac.get("/regime", headers=headers)
        assert r.status_code == 200
        assert r.json()["regime"] == "RISK_ON"

    db.close()
