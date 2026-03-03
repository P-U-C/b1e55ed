"""tests.unit.test_api_producer_capabilities

Unit tests for GET /api/v1/producers/capabilities.

Tests:
1. Returns list of producers with signal_types and schema
2. Healthy vs degraded health determination
3. Empty list when no producers registered
4. Signal types derived from domain
"""

from __future__ import annotations

import os
from datetime import datetime
from types import SimpleNamespace

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from pathlib import Path

import pytest

from api.deps import get_publisher
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
def app_with_producers(tmp_path: Path, test_config):
    db = Database(tmp_path / "brain.db")
    _insert_producer(db, name="ta-prod", domain="technical", last_success_at=datetime.now(tz=UTC).isoformat())
    _insert_producer(db, name="onchain-prod", domain="onchain", consecutive_failures=2)
    _insert_producer(db, name="social-prod", domain="social", last_success_at=datetime.now(tz=UTC).isoformat())

    cfg = test_config.model_copy(update={"api": test_config.api.model_copy(update={"auth_token": "cap-tok"})})
    app = create_app()
    app.state.config = cfg
    app.state.db = db
    yield app, db
    db.close()


@pytest.mark.anyio
async def test_capabilities_returns_list(app_with_producers):
    app, _ = app_with_producers
    headers = {"Authorization": "Bearer cap-tok"}

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/producers/capabilities", headers=headers)

    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 3


@pytest.mark.anyio
async def test_capabilities_fields(app_with_producers):
    """Each capability entry has the required fields."""
    app, _ = app_with_producers
    headers = {"Authorization": "Bearer cap-tok"}

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/producers/capabilities", headers=headers)

    assert r.status_code == 200
    for item in r.json():
        assert "producer_id" in item
        assert "signal_types" in item
        assert isinstance(item["signal_types"], list)
        assert "last_seen" in item
        assert "health" in item
        assert item["health"] in ("healthy", "degraded", "unknown")


@pytest.mark.anyio
async def test_capabilities_healthy_producer(app_with_producers):
    """Producer with no failures and a last_success_at should be healthy."""
    app, _ = app_with_producers
    headers = {"Authorization": "Bearer cap-tok"}

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/producers/capabilities", headers=headers)

    body = r.json()
    ta = next(p for p in body if p["producer_id"] == "ta-prod")
    assert ta["health"] == "healthy"
    assert ta["last_seen"] is not None


@pytest.mark.anyio
async def test_capabilities_degraded_producer(app_with_producers):
    """Producer with consecutive_failures > 0 should be degraded."""
    app, _ = app_with_producers
    headers = {"Authorization": "Bearer cap-tok"}

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/producers/capabilities", headers=headers)

    body = r.json()
    onchain = next(p for p in body if p["producer_id"] == "onchain-prod")
    assert onchain["health"] == "degraded"


@pytest.mark.anyio
async def test_capabilities_signal_types_from_domain(app_with_producers):
    """Signal types should include at least one entry for known domains."""
    app, _ = app_with_producers
    headers = {"Authorization": "Bearer cap-tok"}

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/producers/capabilities", headers=headers)

    body = r.json()
    ta = next(p for p in body if p["producer_id"] == "ta-prod")
    # technical domain → signal.ta.v1
    names = [st["name"] for st in ta["signal_types"]]
    assert "signal.ta.v1" in names


@pytest.mark.anyio
async def test_capabilities_schema_present(app_with_producers):
    """Signal type entries should have a schema dict."""
    app, _ = app_with_producers
    headers = {"Authorization": "Bearer cap-tok"}

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/producers/capabilities", headers=headers)

    body = r.json()
    ta = next(p for p in body if p["producer_id"] == "ta-prod")
    ta_signal = next(st for st in ta["signal_types"] if st["name"] == "signal.ta.v1")
    assert isinstance(ta_signal["schema"], dict)
    assert len(ta_signal["schema"]) > 0  # Should have JSON schema fields


@pytest.mark.anyio
async def test_capabilities_empty_when_no_producers(tmp_path: Path, test_config):
    """Endpoint returns [] when no producers are registered."""
    db = Database(tmp_path / "empty.db")
    cfg = test_config.model_copy(update={"api": test_config.api.model_copy(update={"auth_token": "tok"})})
    app = create_app()
    app.state.config = cfg
    app.state.db = db

    headers = {"Authorization": "Bearer tok"}
    async with make_client(app) as ac:
        r = await ac.get("/api/v1/producers/capabilities", headers=headers)

    assert r.status_code == 200
    assert r.json() == []
    db.close()


def test_get_publisher_uses_community_app_when_config_app_id_zero(test_config, monkeypatch) -> None:
    github_cfg = test_config.publish.github.model_copy(update={"app_id": 0, "token": ""})
    cfg = test_config.model_copy(update={"publish": test_config.publish.model_copy(update={"github": github_cfg})})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config=cfg)))

    monkeypatch.delenv("B1E55ED_GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("B1E55ED_GITHUB_INSTALLATION_ID", raising=False)
    monkeypatch.setenv("B1E55ED_GITHUB_APP_KEY", "dummy-private-key")

    publisher = get_publisher(request)

    assert publisher is not None
