from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from api.main import create_app
from engine.core.database import Database
from tests.unit._api_test_client import make_client

HEADERS = {"Authorization": "Bearer secret"}


def _make_app(temp_dir, test_config):
    test_config = test_config.model_copy(update={"api": test_config.api.model_copy(update={"auth_token": "secret"})})
    db = Database(temp_dir / "brain.db")
    app = create_app()
    app.state.config = test_config
    app.state.db = db
    return app, db


def _insert_position(db: Database, pos_id: str = "pos-1", status: str = "open", entry_price: float = 100.0) -> None:
    with db.conn:
        db.conn.execute(
            """
            INSERT INTO positions (id, platform, asset, direction, entry_price, size_notional, leverage, margin_type,
                                   stop_loss, take_profit, opened_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)
            """,
            (pos_id, "paper", "BTC", "long", entry_price, 1000.0, 1.0, "isolated", None, None, status),
        )


def _insert_public_position(
    db: Database,
    pos_id: str,
    *,
    status: str,
    closed_days_ago: int | None = None,
    realized_pnl: float | None = None,
    platform: str = "paper",
) -> None:
    now = datetime.now(tz=UTC)
    opened_at = now - timedelta(days=1)
    closed_at = now - timedelta(days=closed_days_ago) if closed_days_ago is not None else None

    with db.conn:
        db.conn.execute(
            """
            INSERT INTO positions (
                id, platform, asset, direction, entry_price, size_notional, leverage, margin_type,
                stop_loss, take_profit, opened_at, closed_at, status, realized_pnl,
                regime_at_entry, pcs_at_entry
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pos_id,
                platform,
                "ETH",
                "long",
                2184.28,
                604.85,
                1.0,
                "isolated",
                2074.03,
                2401.51,
                opened_at.isoformat(),
                closed_at.isoformat() if closed_at is not None else None,
                status,
                realized_pnl,
                "BEAR",
                58.83,
            ),
        )


@pytest.mark.anyio
async def test_positions_list_and_get(temp_dir, test_config):
    app, db = _make_app(temp_dir, test_config)
    _insert_position(db)

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/positions", headers=HEADERS)
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 1
        assert items[0]["id"] == "pos-1"

        r2 = await ac.get("/api/v1/positions/pos-1", headers=HEADERS)
        assert r2.status_code == 200
        assert r2.json()["asset"] == "BTC"

    db.close()


@pytest.mark.anyio
async def test_public_positions_endpoint_returns_200_without_auth(temp_dir, test_config):
    app, db = _make_app(temp_dir, test_config)
    _insert_public_position(db, "open-1", status="open")
    _insert_public_position(db, "closed-recent", status="closed", closed_days_ago=2, realized_pnl=-30.5)
    _insert_public_position(db, "closed-old", status="closed", closed_days_ago=8, realized_pnl=5.0)
    _insert_public_position(db, "live-open", status="open", platform="live")

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/positions/public")
        assert r.status_code == 200
        data = r.json()

    assert data["mode"] == "paper"
    assert data["start_balance"] == pytest.approx(test_config.execution.paper_start_balance)

    ids = {item["id"] for item in data["positions"]}
    assert ids == {"open-1", "closed-recent"}

    for item in data["positions"]:
        assert "platform" not in item
        assert "leverage" not in item
        assert "margin_type" not in item

    db.close()


@pytest.mark.anyio
async def test_public_positions_summary_stats_are_computed(temp_dir, test_config):
    app, db = _make_app(temp_dir, test_config)
    _insert_public_position(db, "open-1", status="open")
    _insert_public_position(db, "win-1", status="closed", closed_days_ago=1, realized_pnl=50.0)
    _insert_public_position(db, "loss-1", status="closed", closed_days_ago=2, realized_pnl=-20.0)

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/positions/public")
        assert r.status_code == 200
        summary = r.json()["summary"]

    assert summary["total_positions"] == 3
    assert summary["open"] == 1
    assert summary["closed"] == 2
    assert summary["net_pnl"] == pytest.approx(30.0)
    assert summary["win_rate"] == pytest.approx(0.5)

    db.close()


@pytest.mark.anyio
async def test_close_position_marks_as_closed(temp_dir, test_config):
    app, db = _make_app(temp_dir, test_config)
    _insert_position(db, entry_price=50000.0)

    async with make_client(app) as ac:
        r = await ac.post(
            "/api/v1/positions/pos-1/close",
            headers=HEADERS,
            json={"exit_price": 55000.0, "reason": "test"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "closed"
        assert data["closed_at"] is not None
        # long: (55000 - 50000) * (1000 / 50000) = 5000 * 0.02 = 100
        assert data["realized_pnl"] == pytest.approx(100.0, abs=0.01)

    db.close()


@pytest.mark.anyio
async def test_close_position_defaults_to_flat(temp_dir, test_config):
    """If no exit_price provided, should close at entry (flat, 0 PnL)."""
    app, db = _make_app(temp_dir, test_config)
    _insert_position(db, entry_price=50000.0)

    async with make_client(app) as ac:
        r = await ac.post("/api/v1/positions/pos-1/close", headers=HEADERS, json={})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "closed"
        assert data["realized_pnl"] == pytest.approx(0.0, abs=0.01)

    db.close()


@pytest.mark.anyio
async def test_close_nonexistent_position_returns_404(temp_dir, test_config):
    app, db = _make_app(temp_dir, test_config)

    async with make_client(app) as ac:
        r = await ac.post("/api/v1/positions/no-such/close", headers=HEADERS, json={})
        assert r.status_code == 404

    db.close()


@pytest.mark.anyio
async def test_close_already_closed_position_returns_409(temp_dir, test_config):
    app, db = _make_app(temp_dir, test_config)
    _insert_position(db, status="closed")

    async with make_client(app) as ac:
        r = await ac.post("/api/v1/positions/pos-1/close", headers=HEADERS, json={})
        assert r.status_code == 409

    db.close()


@pytest.mark.anyio
async def test_adjust_stop_updates_stop_loss(temp_dir, test_config):
    app, db = _make_app(temp_dir, test_config)
    _insert_position(db, entry_price=50000.0)

    async with make_client(app) as ac:
        r = await ac.patch(
            "/api/v1/positions/pos-1/stop",
            headers=HEADERS,
            json={"stop_loss": 45000.0},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["stop_loss"] == pytest.approx(45000.0)
        assert data["status"] == "open"

    db.close()


@pytest.mark.anyio
async def test_adjust_target_updates_take_profit(temp_dir, test_config):
    app, db = _make_app(temp_dir, test_config)
    _insert_position(db, entry_price=50000.0)

    async with make_client(app) as ac:
        r = await ac.patch(
            "/api/v1/positions/pos-1/target",
            headers=HEADERS,
            json={"take_profit": 60000.0},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["take_profit"] == pytest.approx(60000.0)
        assert data["status"] == "open"

    db.close()


@pytest.mark.anyio
async def test_adjust_stop_nonexistent_returns_404(temp_dir, test_config):
    app, db = _make_app(temp_dir, test_config)

    async with make_client(app) as ac:
        r = await ac.patch(
            "/api/v1/positions/no-such/stop",
            headers=HEADERS,
            json={"stop_loss": 45000.0},
        )
        assert r.status_code == 404

    db.close()


@pytest.mark.anyio
async def test_adjust_target_nonexistent_returns_404(temp_dir, test_config):
    app, db = _make_app(temp_dir, test_config)

    async with make_client(app) as ac:
        r = await ac.patch(
            "/api/v1/positions/no-such/target",
            headers=HEADERS,
            json={"take_profit": 60000.0},
        )
        assert r.status_code == 404

    db.close()
