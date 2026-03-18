from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from api.main import create_app
from engine.core.database import Database
from tests.unit._api_test_client import make_client

os.environ.setdefault("B1E55ED_INSECURE_OK", "1")
os.environ.setdefault("B1E55ED_DEV_MODE", "1")


def _insert_contributor(
    db: Database,
    *,
    contributor_id: str,
    node_id: str,
    name: str,
    role: str,
    metadata: dict,
) -> None:
    with db.conn:
        db.conn.execute(
            """
            INSERT INTO contributors (id, node_id, name, role, metadata)
            VALUES (?, ?, ?, ?, ?)
            """,
            (contributor_id, node_id, name, role, json.dumps(metadata)),
        )


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
async def test_agent_manifest_returns_200_for_existing_contributor(app_factory, tmp_path: Path):
    db = Database(tmp_path / "brain.db")
    _insert_contributor(
        db,
        contributor_id="contrib-1",
        node_id="node-test-1",
        name="alpha-producer",
        role="producer",
        metadata={"team": "core"},
    )
    app = app_factory(db)
    headers = {"Authorization": "Bearer tok"}

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/agents/node-test-1/manifest", headers=headers)

    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "alpha-producer"
    assert body["identity"]["node_id"] == "node-test-1"
    assert body["identity"]["role"] == "producer"
    assert "agent_id" not in body["identity"]
    assert body["metadata"] == {"team": "core"}
    assert body["url"] == "http://test/api/v1/agents/node-test-1/manifest"
    db.close()


@pytest.mark.anyio
async def test_agent_manifest_query_does_not_reference_agent_id_column(app_factory, tmp_path: Path, monkeypatch):
    db = Database(tmp_path / "brain.db")
    _insert_contributor(
        db,
        contributor_id="contrib-2",
        node_id="node-test-2",
        name="beta-producer",
        role="producer",
        metadata={},
    )

    marker = {"checked": False}
    original_execute = db.execute

    def guarded_execute(sql: str, params: tuple = ()):  # type: ignore[override]
        if "from contributors" in sql.lower():
            marker["checked"] = True
            assert "agent_id" not in sql.lower()
        return original_execute(sql, params)

    monkeypatch.setattr(db, "execute", guarded_execute)

    app = app_factory(db)
    headers = {"Authorization": "Bearer tok"}
    async with make_client(app) as ac:
        r = await ac.get("/api/v1/agents/node-test-2/manifest", headers=headers)

    assert marker["checked"] is True
    assert r.status_code == 200
    db.close()


@pytest.mark.anyio
async def test_agent_manifest_missing_contributor_returns_404(app_factory, tmp_path: Path):
    db = Database(tmp_path / "brain.db")
    app = app_factory(db)
    headers = {"Authorization": "Bearer tok"}

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/agents/missing-node/manifest", headers=headers)

    assert r.status_code == 404
    body = r.json()
    assert body["error"]["code"] == "agent.not_found"
    assert body["error"]["node_id"] == "missing-node"
    db.close()
