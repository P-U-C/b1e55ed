"""tests.unit.test_artifacts

Tests for the artifact store, API endpoints, and distribution pipeline.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from engine.artifacts.distribution import ArtifactDistributor
from engine.artifacts.store import ArtifactRecord, ArtifactStore
from engine.core.database import Database

# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Database:
    """Create a temporary Database for testing."""
    db = Database(tmp_path / "test.db")
    return db


@pytest.fixture()
def store(tmp_db: Database, tmp_path: Path) -> ArtifactStore:
    """Create an ArtifactStore with temporary storage."""
    storage_dir = tmp_path / "artifacts"
    storage_dir.mkdir()
    return ArtifactStore(db=tmp_db, storage_dir=storage_dir)


@pytest.fixture()
def sample_content() -> bytes:
    return b"<html><body><h1>Research Brief</h1></body></html>"


@pytest.fixture()
def sample_artifact(store: ArtifactStore, sample_content: bytes) -> ArtifactRecord:
    """Pre-stored artifact for retrieval tests."""
    return store.store(
        content=sample_content,
        filename="brief-2026-03-07.html",
        content_type="text/html",
        source="deerflow:brief",
        event_id="evt-123",
    )


# ── ArtifactStore Tests ─────────────────────────────────────────────


class TestArtifactStore:
    def test_store_hashes_content_writes_file_records_in_db(self, store: ArtifactStore, sample_content: bytes) -> None:
        record = store.store(
            content=sample_content,
            filename="brief.html",
            content_type="text/html",
            source="deerflow:brief",
        )

        # ID is sha256 of content
        expected_id = hashlib.sha256(sample_content).hexdigest()
        assert record.id == expected_id
        assert record.filename == "brief.html"
        assert record.content_type == "text/html"
        assert record.size_bytes == len(sample_content)
        assert record.source == "deerflow:brief"
        assert record.event_id is None

        # File exists on disk
        assert Path(record.storage_path).exists()
        assert Path(record.storage_path).read_bytes() == sample_content

    def test_store_is_idempotent(self, store: ArtifactStore, sample_content: bytes) -> None:
        r1 = store.store(
            content=sample_content,
            filename="brief.html",
            content_type="text/html",
            source="deerflow:brief",
        )
        r2 = store.store(
            content=sample_content,
            filename="brief.html",
            content_type="text/html",
            source="deerflow:brief",
        )

        # Same content → same ID, no duplicate
        assert r1.id == r2.id

        # Only one row in DB
        count = store._db.conn.execute("SELECT COUNT(*) FROM artifacts WHERE id = ?", (r1.id,)).fetchone()[0]
        assert count == 1

    def test_get_returns_record_by_id(self, store: ArtifactStore, sample_artifact: ArtifactRecord) -> None:
        record = store.get(sample_artifact.id)
        assert record is not None
        assert record.id == sample_artifact.id
        assert record.filename == "brief-2026-03-07.html"
        assert record.content_type == "text/html"
        assert record.source == "deerflow:brief"
        assert record.event_id == "evt-123"

    def test_get_returns_none_for_missing(self, store: ArtifactStore) -> None:
        assert store.get("nonexistent") is None

    def test_link_event_updates_event_id(self, store: ArtifactStore, sample_content: bytes) -> None:
        record = store.store(
            content=sample_content,
            filename="brief.html",
            content_type="text/html",
            source="deerflow:brief",
        )
        assert record.event_id is None

        store.link_event(record.id, "signal-research-v1-abc")

        updated = store.get(record.id)
        assert updated is not None
        assert updated.event_id == "signal-research-v1-abc"

    def test_get_permalink_returns_correct_url(self, store: ArtifactStore, sample_artifact: ArtifactRecord) -> None:
        url = store.get_permalink(sample_artifact.id, "http://localhost:5050/api/v1")
        assert url == f"http://localhost:5050/api/v1/artifacts/{sample_artifact.id}"

    def test_get_permalink_strips_trailing_slash(self, store: ArtifactStore, sample_artifact: ArtifactRecord) -> None:
        url = store.get_permalink(sample_artifact.id, "http://localhost:5050/api/v1/")
        assert url == f"http://localhost:5050/api/v1/artifacts/{sample_artifact.id}"

    def test_list_recent(self, store: ArtifactStore) -> None:
        store.store(b"content1", "file1.txt", "text/plain", "test")
        store.store(b"content2", "file2.txt", "text/plain", "test")
        store.store(b"content3", "file3.txt", "text/plain", "test")

        results = store.list_recent(limit=2)
        assert len(results) == 2
        # Newest first
        assert results[0].filename == "file3.txt"


# ── API Endpoint Tests ───────────────────────────────────────────────


def _make_test_app(store: ArtifactStore) -> FastAPI:
    """Create a minimal FastAPI app with artifact routes for testing."""
    from api.routes.artifacts import _get_store, router

    test_app = FastAPI()
    test_app.dependency_overrides[_get_store] = lambda: store

    # Disable auth for tests
    from api.auth import require_bearer_token

    test_app.dependency_overrides[require_bearer_token] = lambda: None

    test_app.include_router(router)
    return test_app


@pytest.fixture()
def test_app(store: ArtifactStore) -> FastAPI:
    return _make_test_app(store)


@pytest.mark.anyio()
async def test_post_ingest_returns_artifact_id_and_permalink(test_app: FastAPI, store: ArtifactStore) -> None:
    content = b"<html><body>Test brief</body></html>"
    content_b64 = base64.b64encode(content).decode()

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.post(
            "/artifacts/ingest",
            json={
                "content_base64": content_b64,
                "filename": "brief-test.html",
                "content_type": "text/html",
                "source": "deerflow:brief",
                "event_id": "evt-test-123",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "artifact_id" in data
    assert "permalink" in data
    assert data["artifact_id"] == hashlib.sha256(content).hexdigest()


@pytest.mark.anyio()
async def test_get_artifact_returns_content_with_correct_type(test_app: FastAPI, store: ArtifactStore, sample_content: bytes) -> None:
    record = store.store(
        content=sample_content,
        filename="brief.html",
        content_type="text/html",
        source="deerflow:brief",
    )

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.get(f"/artifacts/{record.id}")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/html; charset=utf-8"
    assert resp.content == sample_content


@pytest.mark.anyio()
async def test_get_artifact_404_for_missing(test_app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.get("/artifacts/nonexistent")

    assert resp.status_code == 404


@pytest.mark.anyio()
async def test_get_artifact_meta_returns_metadata_json(test_app: FastAPI, store: ArtifactStore, sample_content: bytes) -> None:
    record = store.store(
        content=sample_content,
        filename="brief-meta.html",
        content_type="text/html",
        source="deerflow:brief",
        event_id="evt-meta-123",
    )

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.get(f"/artifacts/{record.id}/meta")

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == record.id
    assert data["filename"] == "brief-meta.html"
    assert data["content_type"] == "text/html"
    assert data["size_bytes"] == len(sample_content)
    assert data["source"] == "deerflow:brief"
    assert data["event_id"] == "evt-meta-123"
    assert "permalink" in data


# ── Distribution Tests ───────────────────────────────────────────────


class TestArtifactDistributor:
    def test_distribute_succeeds_with_no_channels_configured(self) -> None:
        """Distribution with empty config returns empty list, no error."""
        distributor = ArtifactDistributor(config={})
        record = ArtifactRecord(
            id="abc123",
            filename="test.html",
            content_type="text/html",
            size_bytes=100,
            created_at="2026-03-07T00:00:00Z",
            source="test",
            event_id=None,
            storage_path="/tmp/test.html",
        )

        delivered = distributor.distribute(record, "http://example.com/artifacts/abc123")
        assert delivered == []

    def test_distribute_with_none_config(self) -> None:
        """Distribution with None config returns empty list, no error."""
        distributor = ArtifactDistributor(config=None)
        record = ArtifactRecord(
            id="abc123",
            filename="test.html",
            content_type="text/html",
            size_bytes=100,
            created_at="2026-03-07T00:00:00Z",
            source="test",
            event_id=None,
            storage_path="/tmp/test.html",
        )

        delivered = distributor.distribute(record, "http://example.com/artifacts/abc123")
        assert delivered == []


# ── DeerflowResearchProducer Tests ─────────────────────────────────


class TestDeerflowResearchProducer:
    def test_ingest_artifact_with_sidecar_meta(self, store: ArtifactStore, tmp_path: Path) -> None:
        """Producer ingests artifact with sidecar .meta.json."""
        from engine.producers.deerflow_research import DeerflowResearchProducer

        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        producer = DeerflowResearchProducer(store=store, sandbox_dir=sandbox, require_event_id=True)
        producer.setup()

        content = b"<html>research brief</html>"
        sha256 = hashlib.sha256(content).hexdigest()

        (sandbox / "brief.html").write_bytes(content)
        import json

        (sandbox / "brief.meta.json").write_text(json.dumps({"event_id": "evt-123", "sha256": sha256}))

        results = producer.scan_once()
        assert len(results) == 1
        assert results[0]["artifact_id"] == sha256
        assert results[0]["event_id"] == "evt-123"
        assert "permalink" in results[0]

    def test_reject_artifact_without_event_id(self, store: ArtifactStore, tmp_path: Path) -> None:
        """Producer rejects artifact with no event_id when require_event_id=True."""
        from engine.producers.deerflow_research import DeerflowResearchProducer

        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        producer = DeerflowResearchProducer(store=store, sandbox_dir=sandbox, require_event_id=True)
        producer.setup()

        (sandbox / "orphan.html").write_bytes(b"<html>no event</html>")

        results = producer.scan_once()
        assert results == []  # rejected, not ingested
        assert (sandbox / "rejected" / "orphan.html").exists()

    def test_integrity_check_rejects_tampered_content(self, store: ArtifactStore, tmp_path: Path) -> None:
        """Producer rejects artifact when sha256 in sidecar doesn't match content."""
        import json

        from engine.producers.deerflow_research import DeerflowResearchProducer

        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        producer = DeerflowResearchProducer(store=store, sandbox_dir=sandbox, require_event_id=False)
        producer.setup()

        (sandbox / "tampered.html").write_bytes(b"<html>tampered content</html>")
        (sandbox / "tampered.meta.json").write_text(
            json.dumps(
                {
                    "event_id": "evt-999",
                    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                }
            )
        )

        results = producer.scan_once()
        assert results == []
        assert (sandbox / "rejected" / "tampered.html").exists()

    def test_idempotent_ingestion(self, store: ArtifactStore, tmp_path: Path) -> None:
        """Same content ingested twice produces same artifact_id."""
        import json

        from engine.producers.deerflow_research import DeerflowResearchProducer

        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        producer = DeerflowResearchProducer(store=store, sandbox_dir=sandbox, require_event_id=False)
        producer.setup()

        content = b"<html>same content</html>"
        (sandbox / "first.html").write_bytes(content)
        (sandbox / "first.meta.json").write_text(json.dumps({"event_id": "evt-1"}))

        results1 = producer.scan_once()

        (sandbox / "second.html").write_bytes(content)
        (sandbox / "second.meta.json").write_text(json.dumps({"event_id": "evt-2"}))

        results2 = producer.scan_once()

        assert results1[0]["artifact_id"] == results2[0]["artifact_id"]


class TestIngestEndpointRejection:
    @pytest.mark.anyio()
    async def test_ingest_without_event_id_rejected_by_default(self, store: ArtifactStore, tmp_path: Path) -> None:
        """POST /artifacts/ingest with require_event_id=true (default) and no event_id → 422."""
        test_app = _make_test_app(store)

        content = base64.b64encode(b"<html>orphan</html>").decode()
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            resp = await client.post(
                "/artifacts/ingest",
                json={"content_base64": content, "filename": "orphan.html"},
            )

        assert resp.status_code == 422
        assert resp.json()["error"] == "missing_event_id"

    @pytest.mark.anyio()
    async def test_ingest_without_event_id_allowed_when_disabled(self, store: ArtifactStore, tmp_path: Path) -> None:
        """POST /artifacts/ingest with require_event_id=false allows missing event_id."""
        test_app = _make_test_app(store)

        content = base64.b64encode(b"<html>non-deerflow</html>").decode()
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            resp = await client.post(
                "/artifacts/ingest",
                json={
                    "content_base64": content,
                    "filename": "manual.html",
                    "require_event_id": False,
                },
            )

        assert resp.status_code == 200
        assert "artifact_id" in resp.json()
