from __future__ import annotations

import pytest
from api.main import create_app
from engine.core.database import Database
from engine.security import generate_node_identity
from engine.execution.karma import KarmaEngine
from tests.unit._api_test_client import make_client


@pytest.mark.anyio
async def test_treasury_and_karma_flows(temp_dir, test_config):
    test_config = test_config.model_copy(
        update={
            "api": test_config.api.model_copy(update={"auth_token": "secret"}),
            "karma": test_config.karma.model_copy(update={"treasury_address": "0xabc", "enabled": True, "percentage": 0.01}),
        }
    )

    db = Database(temp_dir / "brain.db")
    identity = generate_node_identity()
    karma = KarmaEngine(config=test_config, db=db, identity=identity)

    # Create intents
    i1 = karma.record_intent(trade_id="t1", realized_pnl_usd=100.0)
    assert i1 is not None

    app = create_app()
    app.state.config = test_config
    app.state.db = db
    app.state.karma = karma

    headers = {"Authorization": "Bearer secret"}
    async with make_client(app) as ac:
        r = await ac.get("/treasury", headers=headers)
        assert r.status_code == 200
        assert r.json()["pending_intents"] == 1

        r2 = await ac.get("/karma/intents", headers=headers)
        assert r2.status_code == 200
        assert len(r2.json()["items"]) == 1

        # Settle
        r3 = await ac.post("/karma/settle", headers=headers, json={"intent_ids": [i1.id]})
        assert r3.status_code == 200

        r4 = await ac.get("/karma/receipts", headers=headers)
        assert r4.status_code == 200
        assert len(r4.json()["items"]) == 1

    db.close()
