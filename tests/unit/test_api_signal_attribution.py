"""tests.unit.test_api_signal_attribution

Unit tests for the signal attribution endpoint.

Tests:
1. Happy path: attribution lookup returns expected fields
2. 404 for unknown signal_id
3. Domain is derived from event type
4. Score is extracted from payload
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from api.main import create_app
from engine.core.database import Database
from engine.core.events import EventType
from tests.unit._api_test_client import make_client

os.environ.setdefault("B1E55ED_INSECURE_OK", "1")
os.environ.setdefault("B1E55ED_DEV_MODE", "1")


@pytest.fixture()
def db_signal(tmp_path: Path) -> tuple[Database, str]:
    """Return (db, signal_event_id) for a seeded signal."""
    db = Database(tmp_path / "brain.db")
    ev = db.append_event(
        event_type=EventType.SIGNAL_SOCIAL_V1,
        payload={
            "symbol": "BTC",
            "score": 8.2,
            "direction": "bullish",
            "source_count": 5,
        },
        source="social-producer",
    )
    return db, ev.id


@pytest.fixture()
def app_factory(test_config):
    def _make(db: Database):
        cfg = test_config.model_copy(update={"api": test_config.api.model_copy(update={"auth_token": "tok"})})
        app = create_app()
        app.state.config = cfg
        app.state.db = db
        return app

    return _make


@pytest.mark.anyio
async def test_attribution_happy_path(db_signal, app_factory):
    db, signal_id = db_signal
    app = app_factory(db)
    headers = {"Authorization": "Bearer tok"}

    async with make_client(app) as ac:
        r = await ac.get(f"/api/v1/signals/{signal_id}/attribution", headers=headers)

    assert r.status_code == 200
    body = r.json()
    assert body["signal_id"] == signal_id
    assert body["producer_id"] == "social-producer"
    assert body["domain"] == "social"
    assert body["score"] == pytest.approx(8.2)
    assert "emitted_at" in body
    assert isinstance(body["linked_trade_ids"], list)
    # No positions in the DB, so outcome should be null
    assert body["outcome"] is None
    db.close()


@pytest.mark.anyio
async def test_attribution_404(app_factory, tmp_path):
    db = Database(tmp_path / "brain2.db")
    app = app_factory(db)
    headers = {"Authorization": "Bearer tok"}

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/signals/nonexistent-id/attribution", headers=headers)

    assert r.status_code == 404
    db.close()


@pytest.mark.anyio
async def test_attribution_domain_extraction(app_factory, tmp_path):
    """Domain should be extracted from event type string."""
    db = Database(tmp_path / "brain3.db")
    ev = db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "ETH"},
        source="my-ta-prod",
    )
    app = app_factory(db)
    headers = {"Authorization": "Bearer tok"}

    async with make_client(app) as ac:
        r = await ac.get(f"/api/v1/signals/{ev.id}/attribution", headers=headers)

    assert r.status_code == 200
    body = r.json()
    assert body["domain"] == "ta"
    assert body["producer_id"] == "my-ta-prod"
    db.close()


@pytest.mark.anyio
async def test_attribution_score_fields(app_factory, tmp_path):
    """Score is extracted from various payload field names."""
    db = Database(tmp_path / "brain4.db")
    # Use 'conviction' field instead of 'score'
    ev = db.append_event(
        event_type=EventType.SIGNAL_CURATOR_V1,
        payload={
            "symbol": "SOL",
            "direction": "bullish",
            "conviction": 9.1,
            "rationale": "strong momentum",
        },
        source="curator",
    )
    app = app_factory(db)
    headers = {"Authorization": "Bearer tok"}

    async with make_client(app) as ac:
        r = await ac.get(f"/api/v1/signals/{ev.id}/attribution", headers=headers)

    assert r.status_code == 200
    assert r.json()["score"] == pytest.approx(9.1)
    db.close()


@pytest.mark.anyio
async def test_attribution_outcome_with_closed_position(app_factory, tmp_path):
    """If a closed position exists, outcome should be populated."""
    from datetime import datetime

    try:
        from datetime import UTC  # py311+
    except ImportError:  # pragma: no cover
        UTC = UTC  # noqa: N806

    db = Database(tmp_path / "brain5.db")
    ev = db.append_event(
        event_type=EventType.SIGNAL_ONCHAIN_V1,
        payload={"symbol": "BTC"},
        source="onchain",
    )

    # Manually insert a contributor row first (FK requirement), then the signal link
    with db.conn:
        db.conn.execute(
            """
            INSERT INTO contributors (id, node_id, name, role)
            VALUES (?, ?, ?, ?)
            """,
            ("contrib-1", "node-test-1", "test-contributor", "producer"),
        )
        db.conn.execute(
            "INSERT INTO contributor_signals (contributor_id, event_id) VALUES (?, ?)",
            ("contrib-1", ev.id),
        )
        db.conn.execute(
            """
            INSERT INTO positions (id, platform, asset, direction, entry_price,
                size_notional, opened_at, closed_at, status, realized_pnl)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "pos-001",
                "paper",
                "BTC",
                "long",
                50000.0,
                1000.0,
                datetime.now(tz=UTC).isoformat(),
                datetime.now(tz=UTC).isoformat(),
                "closed",
                42.5,
            ),
        )

    app = app_factory(db)
    headers = {"Authorization": "Bearer tok"}

    async with make_client(app) as ac:
        r = await ac.get(f"/api/v1/signals/{ev.id}/attribution", headers=headers)

    assert r.status_code == 200
    body = r.json()
    assert "pos-001" in body["linked_trade_ids"]
    assert body["outcome"]["pnl"] == pytest.approx(42.5)
    db.close()
