from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from api.main import create_app
from engine import __version__
from engine.core.database import Database
from engine.core.events import EventType
from tests.unit._api_test_client import make_client


@pytest.mark.anyio
async def test_health_returns_version(temp_dir, test_config):
    app = create_app()
    app.state.config = test_config
    app.state.db = Database(temp_dir / "brain.db")

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/health")
        assert r.status_code == 200
        data = r.json()
        assert data["version"] == __version__
        assert "uptime_seconds" in data

    app.state.db.close()


@pytest.mark.anyio
async def test_health_returns_brain_cycle_status_field(temp_dir, test_config):
    """GET /health always returns the brain_cycle_status field."""
    app = create_app()
    app.state.config = test_config
    app.state.db = Database(temp_dir / "brain.db")

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/health")
        assert r.status_code == 200
        data = r.json()
        assert "brain_cycle_status" in data

    app.state.db.close()


@pytest.mark.anyio
async def test_health_degraded_on_stale_brain_cycle(temp_dir, test_config):
    """Stale brain cycle (2 hours ago) → status: 'degraded'."""
    db = Database(temp_dir / "brain.db")

    # Insert a cycle event with ts 2 hours ago
    stale_ts = datetime.now(UTC) - timedelta(hours=2)
    db.append_event(
        event_type=EventType.BRAIN_CYCLE_V1,
        payload={"reason": "test_stale"},
        ts=stale_ts,
        validate_ts=False,
    )

    app = create_app()
    app.state.config = test_config
    app.state.db = db

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "degraded", f"Expected 'degraded', got {data['status']!r}"
        assert data["brain_cycle_status"] == "stale"

    db.close()


@pytest.mark.anyio
async def test_health_ok_on_fresh_brain_cycle(temp_dir, test_config):
    """Fresh brain cycle (just now) → status: 'ok'."""
    db = Database(temp_dir / "brain.db")

    # Insert a cycle event with ts just now
    fresh_ts = datetime.now(UTC)
    db.append_event(
        event_type=EventType.BRAIN_CYCLE_V1,
        payload={"reason": "test_fresh"},
        ts=fresh_ts,
    )

    app = create_app()
    app.state.config = test_config
    app.state.db = db

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok", f"Expected 'ok', got {data['status']!r}"
        assert data["brain_cycle_status"] == "ok"

    db.close()


@pytest.mark.anyio
async def test_health_unknown_brain_cycle_when_no_events(temp_dir, test_config):
    """No brain cycle events at all → brain_cycle_status: 'unknown'."""
    db = Database(temp_dir / "brain.db")

    app = create_app()
    app.state.config = test_config
    app.state.db = db

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/health")
        assert r.status_code == 200
        data = r.json()
        assert data["brain_cycle_status"] == "unknown"

    db.close()


@pytest.mark.anyio
async def test_health_degraded_on_active_kill_switch(temp_dir, test_config):
    """Active kill switch → status: 'degraded' with kill_switch.status: 'active'."""
    db = Database(temp_dir / "brain.db")

    # Insert an active kill switch event
    db.append_event(
        event_type=EventType.KILL_SWITCH_V1,
        payload={"level": 1, "reason": "test"},
        ts=datetime.now(UTC),
    )
    # Also insert a fresh brain cycle so we isolate the kill-switch degradation
    db.append_event(
        event_type=EventType.BRAIN_CYCLE_V1,
        payload={"reason": "test"},
        ts=datetime.now(UTC),
    )

    app = create_app()
    app.state.config = test_config
    app.state.db = db

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "degraded", f"Expected 'degraded', got {data['status']!r}"
        assert data["kill_switch"]["active"] is True
        assert data["kill_switch"].get("status") == "active"

    db.close()
