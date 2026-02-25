"""tests.unit.test_contributor_attestation

Tests for the contributor attestation API endpoint, including publish info.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from api.main import create_app
from engine.core.contributors import ContributorRegistry
from engine.core.database import Database
from tests.unit._api_test_client import make_client

FAKE_ATTESTATION: dict[str, Any] = {
    "uid": "0xdeadbeef0001",
    "schema_uid": "0xschema",
    "attester": "0xattester",
    "recipient": "0x0000",
    "time": 1700000000,
    "expiration": 0,
    "revocable": True,
    "ref_uid": "0x0000",
    "data": {"nodeId": "node-attest-1"},
    "data_bytes": "0x",
    "signature": "0xsig",
    "onchain": False,
}


def _register_contributor_with_attestation(
    db: Database,
    *,
    node_id: str,
    publish_meta: dict[str, Any] | None = None,
) -> str:
    """Insert a contributor with attestation metadata and return contributor_id."""
    reg = ContributorRegistry(db)
    eas_meta: dict[str, Any] = {
        "uid": FAKE_ATTESTATION["uid"],
        "attestation": FAKE_ATTESTATION,
    }
    if publish_meta is not None:
        eas_meta["publish"] = publish_meta

    c = reg.register(
        node_id=node_id,
        name="Test User",
        role="agent",
        metadata={"eas": eas_meta},
    )
    return c.id


@pytest.mark.anyio
async def test_attestation_response_includes_publish_info(
    temp_dir: Path,
    test_config: Any,
) -> None:
    """Contributor with publish metadata → API returns published.github.issue_url."""
    db = Database(temp_dir / "brain.db")
    publish_meta = {
        "github": {
            "issue_url": "https://github.com/owner/repo/issues/99",
            "issue_number": 99,
            "owner": "owner",
            "repo": "repo",
        }
    }
    cid = _register_contributor_with_attestation(db, node_id="node-attest-pub-1", publish_meta=publish_meta)

    app = create_app()
    app.state.config = test_config
    app.state.db = db

    async with make_client(app) as ac:
        r = await ac.get(f"/api/v1/contributors/{cid}/attestation")

    assert r.status_code == 200
    data = r.json()
    assert data["contributor_id"] == cid
    assert data["uid"] == FAKE_ATTESTATION["uid"]
    assert isinstance(data["attestation"], dict)
    assert data["published"] is not None
    assert data["published"]["github"]["issue_url"] == "https://github.com/owner/repo/issues/99"
    assert data["published"]["github"]["issue_number"] == 99

    db.close()


@pytest.mark.anyio
async def test_attestation_response_null_publish_when_absent(
    temp_dir: Path,
    test_config: Any,
) -> None:
    """Contributor with no publish metadata → published field is null."""
    db = Database(temp_dir / "brain.db")
    cid = _register_contributor_with_attestation(db, node_id="node-attest-nopub-2", publish_meta=None)

    app = create_app()
    app.state.config = test_config
    app.state.db = db

    async with make_client(app) as ac:
        r = await ac.get(f"/api/v1/contributors/{cid}/attestation")

    assert r.status_code == 200
    data = r.json()
    assert data["contributor_id"] == cid
    assert data["uid"] == FAKE_ATTESTATION["uid"]
    assert data["published"] is None

    db.close()


@pytest.mark.anyio
async def test_attestation_not_found_returns_404(
    temp_dir: Path,
    test_config: Any,
) -> None:
    """Contributor without attestation → 404."""
    db = Database(temp_dir / "brain.db")
    reg = ContributorRegistry(db)
    c = reg.register(node_id="node-noattest-3", name="Plain", role="tester", metadata={})

    app = create_app()
    app.state.config = test_config
    app.state.db = db

    async with make_client(app) as ac:
        r = await ac.get(f"/api/v1/contributors/{c.id}/attestation")

    assert r.status_code == 404

    db.close()


@pytest.mark.anyio
async def test_attestation_unknown_contributor_returns_404(
    temp_dir: Path,
    test_config: Any,
) -> None:
    db = Database(temp_dir / "brain.db")

    app = create_app()
    app.state.config = test_config
    app.state.db = db

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/contributors/nonexistent-id/attestation")

    assert r.status_code == 404
    db.close()
