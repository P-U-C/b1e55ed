"""Unit tests for GET /api/v1/capabilities."""

from __future__ import annotations

import os
from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from pathlib import Path

import pytest

from api.main import create_app
from engine.core.database import Database
from tests.unit._api_test_client import make_client

os.environ.setdefault("B1E55ED_INSECURE_OK", "1")
os.environ.setdefault("B1E55ED_DEV_MODE", "1")


def _insert_producer(
    db: Database,
    *,
    name: str,
    domain: str,
    consecutive_failures: int = 0,
    last_success_at: str | None = None,
) -> None:
    from api.routes.producers import _ensure_endpoint_column

    _ensure_endpoint_column(db)
    now = datetime.now(tz=UTC).isoformat()
    with db.conn:
        db.conn.execute(
            """
            INSERT OR REPLACE INTO producer_health
                (name, domain, schedule, endpoint, consecutive_failures, last_success_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (name, domain, "*/15 * * * *", "http://localhost/fake", consecutive_failures, last_success_at, now),
        )


@pytest.fixture()
def app_with_capabilities(tmp_path: Path, test_config):
    db = Database(tmp_path / "brain.db")
    _insert_producer(db, name="ta-prod", domain="technical", last_success_at=datetime.now(tz=UTC).isoformat())
    _insert_producer(db, name="social-prod", domain="social")

    # Seed non-signal domain event to ensure event_domains include more than defaults.
    db.append_event(
        event_type="brain.cycle.v1",
        payload={"ok": True},
        source="brain",
    )

    cfg = test_config.model_copy(update={"api": test_config.api.model_copy(update={"auth_token": "cap-tok"})})
    app = create_app()
    app.state.config = cfg
    app.state.db = db
    yield app, db
    db.close()


@pytest.mark.anyio
async def test_capabilities_returns_tools_domains_and_producers(app_with_capabilities):
    app, _ = app_with_capabilities
    headers = {"Authorization": "Bearer cap-tok"}

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/capabilities", headers=headers)

    assert r.status_code == 200
    body = r.json()

    tool_names = {t["name"] for t in body["tools"]}
    assert "get_brain_status" in tool_names
    assert "emit_producer_signal" in tool_names

    assert "signal" in body["event_domains"]
    assert "brain" in body["event_domains"]

    producers = {p["producer_id"] for p in body["producers"]}
    assert producers == {"social-prod", "ta-prod"}


@pytest.mark.anyio
async def test_capabilities_requires_auth(app_with_capabilities):
    app, _ = app_with_capabilities

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/capabilities")

    assert r.status_code == 401
    assert r.json()["error"]["code"] == "auth.missing_token"
