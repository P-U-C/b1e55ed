"""Tests that the embedded API brain scheduler is disabled in daemon mode.

When B1E55ED_DAEMON_MODE=1, the API must not create a brain-cycle-scheduler
asyncio task — the daemon owns the scheduler exclusively.

Note: We trigger the lifespan via `app.router.lifespan_context(app)` because
httpx's ASGITransport does not run the FastAPI lifespan context.
"""

from __future__ import annotations

import asyncio

import pytest

from api.main import create_app
from engine.core.database import Database


@pytest.mark.anyio
async def test_api_scheduler_disabled_in_daemon_mode(temp_dir, test_config, monkeypatch):
    """Lifespan must NOT create brain-cycle-scheduler task when daemon mode is active."""
    monkeypatch.setenv("B1E55ED_DAEMON_MODE", "1")

    app = create_app()
    app.state.config = test_config
    app.state.db = Database(temp_dir / "brain.db")

    async with app.router.lifespan_context(app):
        task_names = {t.get_name() for t in asyncio.all_tasks()}

    app.state.db.close()

    assert "brain-cycle-scheduler" not in task_names, "brain-cycle-scheduler task must NOT be created when B1E55ED_DAEMON_MODE=1"


@pytest.mark.anyio
async def test_api_scheduler_runs_without_daemon_mode(temp_dir, test_config, monkeypatch):
    """Lifespan SHOULD create brain-cycle-scheduler task in standalone (non-daemon) mode."""
    monkeypatch.delenv("B1E55ED_DAEMON_MODE", raising=False)

    app = create_app()
    app.state.config = test_config
    app.state.db = Database(temp_dir / "brain.db")

    async with app.router.lifespan_context(app):
        task_names = {t.get_name() for t in asyncio.all_tasks()}

    app.state.db.close()

    assert "brain-cycle-scheduler" in task_names, "brain-cycle-scheduler task MUST be created in standalone mode (no daemon)"
