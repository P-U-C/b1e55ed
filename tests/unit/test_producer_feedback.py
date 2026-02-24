"""tests.unit.test_producer_feedback

Tests for the producer feedback analytics endpoint.
  POST /api/v1/producers/{producer_id}/feedback
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from api.main import create_app
from engine.core.database import Database
from tests.unit._api_test_client import make_client

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def _app_and_db(temp_dir, test_config):
    test_config = test_config.model_copy(update={"api": test_config.api.model_copy(update={"auth_token": "secret"})})
    db = Database(temp_dir / "brain.db")
    app = create_app()
    app.state.config = test_config
    app.state.db = db
    yield app, db
    db.close()


_H = {"Authorization": "Bearer secret"}


# ---------------------------------------------------------------------------
# No signals for producer
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_feedback_no_signals(_app_and_db):
    app, _ = _app_and_db
    async with make_client(app) as ac:
        r = await ac.post(
            "/api/v1/producers/unknown_producer/feedback",
            json={"window_hours": 24},
            headers=_H,
        )

    assert r.status_code == 200
    body = r.json()
    assert body["producer_id"] == "unknown_producer"
    assert body["signals_evaluated"] == 0
    assert body["hit_rate"] == 0.0
    assert body["top_miss"] == []


# ---------------------------------------------------------------------------
# Signals evaluated — all misses (no_fill)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_feedback_all_miss(_app_and_db):
    app, db = _app_and_db

    for i in range(3):
        db.append_event(
            event_type="signal.ta.v1",
            payload={"symbol": "BTC", "rsi_14": float(40 + i), "conviction": 0.7},
            source="my_producer",
        )

    async with make_client(app) as ac:
        r = await ac.post(
            "/api/v1/producers/my_producer/feedback",
            json={"window_hours": 24},
            headers=_H,
        )

    assert r.status_code == 200
    body = r.json()
    assert body["producer_id"] == "my_producer"
    assert body["signals_evaluated"] == 3
    assert body["hit_rate"] == 0.0
    assert len(body["top_miss"]) == 3
    for m in body["top_miss"]:
        assert m["outcome"] == "no_fill"


# ---------------------------------------------------------------------------
# Mixed signals — some hits via position PnL
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_feedback_mixed_hit_rate(_app_and_db):
    app, db = _app_and_db

    now = datetime.now(tz=UTC)

    # Signal 1: will be marked as a hit (profit)
    db.append_event(
        event_type="signal.ta.v1",
        payload={"symbol": "BTC", "conviction": 0.8},
        source="mixed_producer",
        ts=now,
    )

    # Insert a position opened within 5 minutes of signal 1 with profit
    pos_id = "pos-hit-1"
    opened_at = (now + timedelta(seconds=30)).isoformat()
    with db.conn:
        db.conn.execute(
            """
            INSERT INTO positions (id, platform, asset, direction, entry_price, size_notional,
                                   leverage, opened_at, status, realized_pnl)
            VALUES (?, 'paper', 'BTC', 'long', 50000.0, 1000.0, 1.0, ?, 'closed', 100.0)
            """,
            (pos_id, opened_at),
        )
    # Also insert the position_opened event so the DB query can correlate
    db.append_event(
        event_type="execution.position_opened.v1",
        payload={"position_id": pos_id, "asset": "BTC"},
        source="oms",
        ts=now + timedelta(seconds=30),
    )

    # Signal 2: no fill → miss
    db.append_event(
        event_type="signal.ta.v1",
        payload={"symbol": "ETH", "conviction": 0.5},
        source="mixed_producer",
        ts=now - timedelta(hours=1),
    )

    async with make_client(app) as ac:
        r = await ac.post(
            "/api/v1/producers/mixed_producer/feedback",
            json={"window_hours": 24},
            headers=_H,
        )

    assert r.status_code == 200
    body = r.json()
    assert body["signals_evaluated"] == 2
    # Hit rate should be 0.5 (1 hit, 1 miss)
    assert body["hit_rate"] == 0.5
    assert len(body["top_miss"]) == 1
    assert body["top_miss"][0]["outcome"] == "no_fill"


# ---------------------------------------------------------------------------
# Window hours filter
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_feedback_window_filter(_app_and_db):
    app, db = _app_and_db

    now = datetime.now(tz=UTC)

    # Signal inside window (1 hour ago)
    db.append_event(
        event_type="signal.onchain.v1",
        payload={"symbol": "BTC"},
        source="window_producer",
        ts=now - timedelta(hours=1),
    )

    # Signal outside window (48 hours ago), window is 24 hours
    old_ts = now - timedelta(hours=48)
    with db.conn:
        # Insert directly to avoid hash-chain issues with past timestamps
        import uuid as _uuid

        old_id = str(_uuid.uuid4())
        db.conn.execute(
            """
            INSERT INTO events (id, type, ts, source, payload, hash)
            VALUES (?, 'signal.onchain.v1', ?, 'window_producer', '{"symbol": "BTC"}', ?)
            """,
            (old_id, old_ts.isoformat(), f"fakehash-{old_id}"),
        )
        db.conn.commit()

    async with make_client(app) as ac:
        r = await ac.post(
            "/api/v1/producers/window_producer/feedback",
            json={"window_hours": 24},
            headers=_H,
        )

    body = r.json()
    assert body["signals_evaluated"] == 1  # Only the recent one


# ---------------------------------------------------------------------------
# Default window (24h)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_feedback_default_window(_app_and_db):
    app, db = _app_and_db

    db.append_event(
        event_type="signal.sentiment.v1",
        payload={"symbol": "SOL"},
        source="default_window_producer",
    )

    async with make_client(app) as ac:
        r = await ac.post(
            "/api/v1/producers/default_window_producer/feedback",
            json={},  # no window_hours → defaults to 24
            headers=_H,
        )

    body = r.json()
    assert body["window_hours"] == 24
    assert body["signals_evaluated"] == 1


# ---------------------------------------------------------------------------
# Auth required
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_feedback_auth_required(_app_and_db):
    app, _ = _app_and_db
    async with make_client(app) as ac:
        r = await ac.post(
            "/api/v1/producers/some_producer/feedback",
            json={"window_hours": 24},
        )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# top_miss max 10
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_feedback_top_miss_capped_at_10(_app_and_db):
    app, db = _app_and_db

    for i in range(15):
        db.append_event(
            event_type="signal.ta.v1",
            payload={"symbol": "BTC", "conviction": float(i) / 15.0},
            source="capped_producer",
        )

    async with make_client(app) as ac:
        r = await ac.post(
            "/api/v1/producers/capped_producer/feedback",
            json={"window_hours": 24},
            headers=_H,
        )

    body = r.json()
    assert body["signals_evaluated"] == 15
    assert len(body["top_miss"]) <= 10
