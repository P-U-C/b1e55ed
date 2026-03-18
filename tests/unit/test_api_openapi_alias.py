"""Tests for OpenAPI discovery paths."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from api.main import create_app
from engine.core.database import Database
from tests.unit._api_test_client import make_client

os.environ.setdefault("B1E55ED_INSECURE_OK", "1")
os.environ.setdefault("B1E55ED_DEV_MODE", "1")


@pytest.fixture()
def app_with_auth(tmp_path: Path, test_config):
    db = Database(tmp_path / "brain.db")
    cfg = test_config.model_copy(update={"api": test_config.api.model_copy(update={"auth_token": "tok"})})
    app = create_app()
    app.state.config = cfg
    app.state.db = db
    yield app
    db.close()


@pytest.mark.anyio
async def test_openapi_alias_matches_canonical_spec(app_with_auth):
    async with make_client(app_with_auth) as ac:
        canonical = await ac.get("/openapi.json")
        alias = await ac.get("/api/v1/openapi.json")

    assert canonical.status_code == 200
    assert alias.status_code == 200

    canonical_body = canonical.json()
    alias_body = alias.json()

    assert alias_body["openapi"] == canonical_body["openapi"]
    assert alias_body["info"] == canonical_body["info"]
    assert set(alias_body["paths"].keys()) == set(canonical_body["paths"].keys())
