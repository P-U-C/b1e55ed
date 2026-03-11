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


@pytest.mark.anyio
async def test_submit_signal_defaults_source_to_node_id_when_blank(temp_dir, test_config):
    test_config = test_config.model_copy(update={"api": test_config.api.model_copy(update={"auth_token": "secret"})})

    db = Database(temp_dir / "brain-submit.db")
    app = create_app()
    app.state.config = test_config
    app.state.db = db

    headers = {"Authorization": "Bearer secret"}
    node_id = "node-submit-source-1"

    async with make_client(app) as ac:
        reg = await ac.post(
            "/api/v1/contributors/register",
            headers=headers,
            json={"node_id": node_id, "name": "SubmitAgent", "role": "agent", "metadata": {}},
        )
        assert reg.status_code == 200, reg.text

        submit = await ac.post(
            "/api/v1/signals/submit",
            headers=headers,
            json={
                "event_type": "signal.curator.v1",
                "node_id": node_id,
                "source": "   ",
                "payload": {"symbol": "BTC", "direction": "bullish", "conviction": 6.0},
            },
        )
        assert submit.status_code == 200, submit.text
        event_id = submit.json()["event_id"]

    row = db.execute("SELECT source FROM events WHERE id = ?", (event_id,)).fetchone()
    assert row is not None
    assert str(row[0]) == node_id
    db.close()
