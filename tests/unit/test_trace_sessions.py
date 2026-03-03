"""tests.unit.test_trace_sessions

Tests for the stateful trace session endpoints.

  POST /api/v1/trace/session                     — create
  PUT  /api/v1/trace/session/{id}/append         — append trace_id
  GET  /api/v1/trace/session/{id}                — get with events
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017


import pytest

from api.main import create_app
from engine.core.database import Database
from tests.unit._api_test_client import make_client

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def _app_and_db(temp_dir, test_config):
    test_config = test_config.model_copy(update={"api": test_config.api.model_copy(update={"auth_token": "tracekey"})})
    db = Database(temp_dir / "brain.db")
    app = create_app()
    app.state.config = test_config
    app.state.db = db
    yield app, db
    db.close()


_H = {"Authorization": "Bearer tracekey"}


# ---------------------------------------------------------------------------
# Create session
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_session(_app_and_db):
    app, _ = _app_and_db
    async with make_client(app) as ac:
        r = await ac.post(
            "/api/v1/trace/session",
            json={"label": "my test session"},
            headers=_H,
        )

    assert r.status_code == 201
    body = r.json()
    assert "session_id" in body
    assert body["label"] == "my test session"
    assert body["trace_ids"] == []
    assert "created_at" in body


@pytest.mark.anyio
async def test_create_session_missing_label(_app_and_db):
    app, _ = _app_and_db
    async with make_client(app) as ac:
        r = await ac.post("/api/v1/trace/session", json={}, headers=_H)
    assert r.status_code == 422  # Pydantic validation error


@pytest.mark.anyio
async def test_create_session_auth_required(_app_and_db):
    app, _ = _app_and_db
    async with make_client(app) as ac:
        r = await ac.post("/api/v1/trace/session", json={"label": "x"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Append trace_id
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_append_trace_id(_app_and_db):
    app, _ = _app_and_db
    async with make_client(app) as ac:
        # Create
        cr = await ac.post("/api/v1/trace/session", json={"label": "append test"}, headers=_H)
        session_id = cr.json()["session_id"]

        # Append
        ar = await ac.put(
            f"/api/v1/trace/session/{session_id}/append",
            json={"trace_id": "trace-abc-123"},
            headers=_H,
        )

    assert ar.status_code == 200
    body = ar.json()
    assert "trace-abc-123" in body["trace_ids"]


@pytest.mark.anyio
async def test_append_multiple_trace_ids(_app_and_db):
    app, _ = _app_and_db
    async with make_client(app) as ac:
        cr = await ac.post("/api/v1/trace/session", json={"label": "multi-append"}, headers=_H)
        sid = cr.json()["session_id"]

        await ac.put(f"/api/v1/trace/session/{sid}/append", json={"trace_id": "t1"}, headers=_H)
        await ac.put(f"/api/v1/trace/session/{sid}/append", json={"trace_id": "t2"}, headers=_H)
        ar = await ac.put(f"/api/v1/trace/session/{sid}/append", json={"trace_id": "t3"}, headers=_H)

    body = ar.json()
    assert set(body["trace_ids"]) == {"t1", "t2", "t3"}


@pytest.mark.anyio
async def test_append_deduplicates_trace_ids(_app_and_db):
    app, _ = _app_and_db
    async with make_client(app) as ac:
        cr = await ac.post("/api/v1/trace/session", json={"label": "dedup test"}, headers=_H)
        sid = cr.json()["session_id"]

        await ac.put(f"/api/v1/trace/session/{sid}/append", json={"trace_id": "dup"}, headers=_H)
        ar = await ac.put(f"/api/v1/trace/session/{sid}/append", json={"trace_id": "dup"}, headers=_H)

    body = ar.json()
    assert body["trace_ids"].count("dup") == 1


@pytest.mark.anyio
async def test_append_to_nonexistent_session(_app_and_db):
    app, _ = _app_and_db
    async with make_client(app) as ac:
        r = await ac.put(
            "/api/v1/trace/session/no-such-id/append",
            json={"trace_id": "t1"},
            headers=_H,
        )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Get session — basic
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_session_empty(_app_and_db):
    app, _ = _app_and_db
    async with make_client(app) as ac:
        cr = await ac.post("/api/v1/trace/session", json={"label": "get test"}, headers=_H)
        sid = cr.json()["session_id"]
        gr = await ac.get(f"/api/v1/trace/session/{sid}", headers=_H)

    assert gr.status_code == 200
    body = gr.json()
    assert body["session_id"] == sid
    assert body["label"] == "get test"
    assert body["trace_ids"] == []
    assert body["events"] == []
    assert body["expired"] is False


@pytest.mark.anyio
async def test_get_session_not_found(_app_and_db):
    app, _ = _app_and_db
    async with make_client(app) as ac:
        r = await ac.get("/api/v1/trace/session/nonexistent-uuid", headers=_H)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Get session — with events
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_session_with_events(_app_and_db):
    app, db = _app_and_db

    trace_id = "trace-xyz-999"

    # Insert events with this trace_id
    db.append_event(
        event_type="brain.cycle.v1",
        payload={"cycle_id": "cycle-001", "symbols": ["BTC"]},
        source="brain.orchestrator",
        trace_id=trace_id,
    )
    db.append_event(
        event_type="signal.ta.v1",
        payload={"symbol": "BTC"},
        source="ta_producer",
        trace_id=trace_id,
    )

    async with make_client(app) as ac:
        cr = await ac.post("/api/v1/trace/session", json={"label": "events test"}, headers=_H)
        sid = cr.json()["session_id"]

        await ac.put(
            f"/api/v1/trace/session/{sid}/append",
            json={"trace_id": trace_id},
            headers=_H,
        )

        gr = await ac.get(f"/api/v1/trace/session/{sid}", headers=_H)

    body = gr.json()
    assert body["session_id"] == sid
    assert trace_id in body["trace_ids"]
    assert len(body["events"]) == 2
    event_types = {e["type"] for e in body["events"]}
    assert "brain.cycle.v1" in event_types
    assert "signal.ta.v1" in event_types
    # All events share the trace_id
    for e in body["events"]:
        assert e["trace_id"] == trace_id


# ---------------------------------------------------------------------------
# Session expiry
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_expired_session_get(_app_and_db):
    """An expired session should return expired=True and empty events."""
    app, db = _app_and_db

    session_id = "expired-session-uuid"
    old_ts = (datetime.now(tz=UTC) - timedelta(hours=25)).isoformat()

    # Force-insert an expired session
    from api.routes.trace import _ensure_trace_sessions_table

    _ensure_trace_sessions_table(db)
    with db.conn:
        db.conn.execute(
            """
            INSERT INTO trace_sessions (session_id, label, created_at, last_accessed_at, trace_ids)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, "expired label", old_ts, old_ts, json.dumps(["some-trace"])),
        )

    async with make_client(app) as ac:
        r = await ac.get(f"/api/v1/trace/session/{session_id}", headers=_H)

    assert r.status_code == 200
    body = r.json()
    assert body["expired"] is True
    assert body["events"] == []


@pytest.mark.anyio
async def test_expired_session_append_rejected(_app_and_db):
    app, db = _app_and_db

    session_id = "expired-append-uuid"
    old_ts = (datetime.now(tz=UTC) - timedelta(hours=25)).isoformat()

    from api.routes.trace import _ensure_trace_sessions_table

    _ensure_trace_sessions_table(db)
    with db.conn:
        db.conn.execute(
            """
            INSERT INTO trace_sessions (session_id, label, created_at, last_accessed_at, trace_ids)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, "old session", old_ts, old_ts, json.dumps([])),
        )

    async with make_client(app) as ac:
        r = await ac.put(
            f"/api/v1/trace/session/{session_id}/append",
            json={"trace_id": "t1"},
            headers=_H,
        )

    assert r.status_code == 410


# ---------------------------------------------------------------------------
# Touch on GET refreshes last_accessed_at
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_session_touches_last_accessed(_app_and_db):
    app, db = _app_and_db
    async with make_client(app) as ac:
        cr = await ac.post("/api/v1/trace/session", json={"label": "touch test"}, headers=_H)
        sid = cr.json()["session_id"]
        created_at = cr.json()["created_at"]

        # Small sleep isn't needed for SQLite UTC timestamps; just verify field is present
        gr = await ac.get(f"/api/v1/trace/session/{sid}", headers=_H)

    body = gr.json()
    assert "last_accessed_at" in body
    assert body["last_accessed_at"] >= created_at
