from __future__ import annotations

import pytest

from api.main import create_app
from engine.core.database import Database
from tests.unit._api_test_client import make_client


@pytest.mark.anyio
async def test_positions_list_and_get(temp_dir, test_config):
    test_config = test_config.model_copy(update={"api": test_config.api.model_copy(update={"auth_token": "secret"})})

    db = Database(temp_dir / "brain.db")
    with db.conn:
        db.conn.execute(
            """
            INSERT INTO positions (id, platform, asset, direction, entry_price, size_notional, leverage, margin_type,
                                   stop_loss, take_profit, opened_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), 'open')
            """,
            ("pos-1", "paper", "BTC", "long", 100.0, 1000.0, 1.0, "isolated", None, None),
        )

    app = create_app()
    app.state.config = test_config
    app.state.db = db

    headers = {"Authorization": "Bearer secret"}
    async with make_client(app) as ac:
        r = await ac.get("/api/v1/positions", headers=headers)
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 1
        assert items[0]["id"] == "pos-1"

        r2 = await ac.get("/api/v1/positions/pos-1", headers=headers)
        assert r2.status_code == 200
        assert r2.json()["asset"] == "BTC"

    db.close()
