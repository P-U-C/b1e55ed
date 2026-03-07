"""engine.artifacts.store

Artifact storage for DeerFlow-generated research outputs.

Artifacts are hashed, stored, and linked to the events that produced them.
The hash is the identity — same content, same artifact. Idempotent by design.
"""

from __future__ import annotations

import hashlib
import mimetypes
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.core.database import Database

try:
    from datetime import UTC
except ImportError:  # pragma: no cover
    UTC = UTC  # noqa: N806


@dataclass(frozen=True)
class ArtifactRecord:
    """Immutable record of a stored artifact."""

    id: str
    filename: str
    content_type: str
    size_bytes: int
    created_at: str
    source: str
    event_id: str | None
    storage_path: str


_ARTIFACTS_SCHEMA = """\
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    source TEXT,
    event_id TEXT,
    storage_path TEXT NOT NULL
);
"""


class ArtifactStore:
    """Hash-addressed artifact storage backed by SQLite + local filesystem."""

    def __init__(self, db: Database, storage_dir: Path | None = None) -> None:
        self._db = db
        self._storage_dir = storage_dir or self._default_storage_dir()
        self._lock = threading.Lock()
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    @staticmethod
    def _default_storage_dir() -> Path:
        from engine.core.paths import b1e55ed_dir

        return b1e55ed_dir() / "artifacts"

    def _ensure_schema(self) -> None:
        """Create artifacts table if not exists."""
        with self._lock:
            self._db.conn.executescript(_ARTIFACTS_SCHEMA)

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def store(
        self,
        content: bytes,
        filename: str,
        content_type: str,
        source: str,
        event_id: str | None = None,
    ) -> ArtifactRecord:
        """Hash content, store to disk, record in DB. Returns ArtifactRecord.

        Idempotent: storing the same content twice returns the same record
        without creating duplicate files or rows.
        """
        artifact_id = hashlib.sha256(content).hexdigest()

        # Check for existing record (idempotency)
        existing = self.get(artifact_id)
        if existing is not None:
            return existing

        # Determine file suffix from filename or content_type
        suffix = Path(filename).suffix or (mimetypes.guess_extension(content_type) or "")

        # Shard storage: storage_dir / first_2_chars / artifact_id + suffix
        shard_dir = self._storage_dir / artifact_id[:2]
        shard_dir.mkdir(parents=True, exist_ok=True)
        file_path = shard_dir / (artifact_id + suffix)

        # Write content to disk
        file_path.write_bytes(content)

        now = datetime.now(tz=UTC).isoformat()

        # Insert into DB
        with self._lock:
            try:
                self._db.conn.execute(
                    "INSERT INTO artifacts (id, filename, content_type, size_bytes, "
                    "created_at, source, event_id, storage_path) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        artifact_id,
                        filename,
                        content_type,
                        len(content),
                        now,
                        source,
                        event_id,
                        str(file_path),
                    ),
                )
                self._db.conn.commit()
            except sqlite3.IntegrityError:
                # Race condition: another thread inserted between get() and insert
                existing = self.get(artifact_id)
                if existing is not None:
                    return existing

        return ArtifactRecord(
            id=artifact_id,
            filename=filename,
            content_type=content_type,
            size_bytes=len(content),
            created_at=now,
            source=source,
            event_id=event_id,
            storage_path=str(file_path),
        )

    def get(self, artifact_id: str) -> ArtifactRecord | None:
        """Retrieve artifact record by ID."""
        row = self._db.conn.execute(
            "SELECT id, filename, content_type, size_bytes, created_at, source, event_id, storage_path FROM artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()

        if row is None:
            return None

        return ArtifactRecord(
            id=row[0],
            filename=row[1],
            content_type=row[2],
            size_bytes=row[3],
            created_at=row[4],
            source=row[5],
            event_id=row[6],
            storage_path=row[7],
        )

    def link_event(self, artifact_id: str, event_id: str) -> None:
        """Link an artifact to a b1e55ed event."""
        with self._lock:
            self._db.conn.execute(
                "UPDATE artifacts SET event_id = ? WHERE id = ?",
                (event_id, artifact_id),
            )
            self._db.conn.commit()

    def get_permalink(self, artifact_id: str, base_url: str) -> str:
        """Returns permalink URL for artifact.

        base_url is expected to be the API base (e.g. http://localhost:5050/api/v1).
        """
        base = base_url.rstrip("/")
        return f"{base}/artifacts/{artifact_id}"

    def list_recent(self, limit: int = 20) -> list[ArtifactRecord]:
        """List recent artifacts, newest first."""
        rows = self._db.conn.execute(
            "SELECT id, filename, content_type, size_bytes, created_at, source, event_id, storage_path FROM artifacts ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

        return [
            ArtifactRecord(
                id=r[0],
                filename=r[1],
                content_type=r[2],
                size_bytes=r[3],
                created_at=r[4],
                source=r[5],
                event_id=r[6],
                storage_path=r[7],
            )
            for r in rows
        ]
