from __future__ import annotations

import pytest

from api.main import create_app
from engine.core.database import Database
from engine.core.events import EventType
from tests.unit._api_test_client import make_client


@pytest.mark.anyio
async def test_signals_paginated(temp_dir, test_config):
    test_config = test_config.model_copy(update={"api": test_config.api.model_copy(update={"auth_token": "secret"})})

    db = Database(temp_dir / "brain.db")
    db.append_event(event_type=EventType.SIGNAL_TA_V1, payload={"symbol": "BTC"})
    db.append_event(event_type=EventType.SIGNAL_ONCHAIN_V1, payload={"symbol": "ETH"})

    app = create_app()
    app.state.config = test_config
    app.state.db = db

    headers = {"Authorization": "Bearer secret"}
    async with make_client(app) as ac:
        r = await ac.get("/api/v1/signals?limit=1&offset=0", headers=headers)
        assert r.status_code == 200
        js = r.json()
        assert js["total"] >= 2
        assert len(js["items"]) == 1

        r2 = await ac.get("/api/v1/signals?domain=ta", headers=headers)
        assert r2.status_code == 200
        js2 = r2.json()
        assert all(item["type"].startswith("signal.ta") for item in js2["items"])

    db.close()
