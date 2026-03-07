"""engine.producers.deerflow_research

DeerFlow Research Artifact Producer.

Watches a configurable sandbox directory for new DeerFlow-generated artifacts
(HTML briefs, markdown reports, JSON summaries) and ingests them into the
b1e55ed artifact store with SHA-256 integrity verification.

Configuration (in b1e55ed config YAML or env):
    DEERFLOW_SANDBOX_DIR  — path to watch (default: ~/.b1e55ed/deerflow/sandbox)
    DEERFLOW_POLL_INTERVAL — seconds between scans (default: 30)

Each artifact file must either:
  - Have a sidecar .meta.json with {"event_id": "...", "source": "deerflow:brief"}
  - Or be named with a pattern: {event_id}_{filename} (event_id extracted from prefix)

Artifacts without a resolvable event_id are quarantined to sandbox/rejected/
with a reason file explaining the rejection.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from engine.artifacts.distribution import ArtifactDistributor
from engine.artifacts.store import ArtifactStore

logger = logging.getLogger(__name__)

DEFAULT_SANDBOX_DIR = Path.home() / ".b1e55ed" / "deerflow" / "sandbox"
DEFAULT_POLL_INTERVAL = 30  # seconds
SUPPORTED_EXTENSIONS = {".html", ".md", ".json", ".txt", ".pdf"}


# Maxwell's demon (1867) was a thought experiment: an entity that watches,
# sorts, and decides what passes through. Unix named its background processes
# 'daemons' after this. This producer is one — watching the sandbox gate,
# verifying integrity, rejecting the unlinked. The demon's dilemma was entropy.
# Ours is provenance.
class DeerflowResearchProducer:
    """Watches a sandbox directory and ingests DeerFlow artifacts into the store."""

    def __init__(
        self,
        store: ArtifactStore,
        distributor: ArtifactDistributor | None = None,
        sandbox_dir: Path | None = None,
        poll_interval: int | None = None,
        base_url: str = "http://localhost:5050/api/v1",
        require_event_id: bool = True,
    ) -> None:
        self._store = store
        self._distributor = distributor
        self._sandbox_dir = sandbox_dir or Path(os.getenv("DEERFLOW_SANDBOX_DIR", str(DEFAULT_SANDBOX_DIR)))
        self._poll_interval = poll_interval or int(os.getenv("DEERFLOW_POLL_INTERVAL", str(DEFAULT_POLL_INTERVAL)))
        self._base_url = base_url
        self._require_event_id = require_event_id
        self._processed_dir = self._sandbox_dir / "processed"
        self._rejected_dir = self._sandbox_dir / "rejected"
        self._running = False

    def setup(self) -> None:
        """Create sandbox directory structure."""
        self._sandbox_dir.mkdir(parents=True, exist_ok=True)
        self._processed_dir.mkdir(exist_ok=True)
        self._rejected_dir.mkdir(exist_ok=True)

    def _load_meta(self, artifact_path: Path) -> dict[str, Any]:
        """Load sidecar .meta.json if present."""
        meta_path = artifact_path.with_suffix(".meta.json")
        if meta_path.exists():
            try:
                return json.loads(meta_path.read_text())
            except json.JSONDecodeError:
                logger.warning("Malformed .meta.json for %s", artifact_path.name)
        return {}

    def _extract_event_id(self, artifact_path: Path, meta: dict[str, Any]) -> str | None:
        """Resolve event_id from sidecar meta or filename prefix."""
        # Sidecar takes priority
        if "event_id" in meta:
            return meta["event_id"]

        # Filename pattern: {event_id}_{rest} where event_id starts with "evt-"
        name = artifact_path.stem
        if "_" in name and name.split("_")[0].startswith("evt-"):
            return name.split("_")[0]

        return None

    def _reject(self, artifact_path: Path, reason: str) -> None:
        """Move artifact to rejected/ with a reason file."""
        dest = self._rejected_dir / artifact_path.name
        artifact_path.rename(dest)
        reason_file = self._rejected_dir / f"{artifact_path.name}.rejected.txt"
        reason_file.write_text(f"Rejected at: {datetime.now(UTC).isoformat()}\nReason: {reason}\n")
        logger.warning("Rejected artifact %s: %s", artifact_path.name, reason)

    def _verify_integrity(self, content: bytes, meta: dict[str, Any]) -> bool:
        """Verify SHA-256 if declared in meta. Returns True if ok."""
        declared = meta.get("sha256")
        if not declared:
            return True  # no declared hash — skip verification
        actual = hashlib.sha256(content).hexdigest()
        if actual != declared:
            logger.error(
                "Integrity check FAILED for declared sha256=%s, actual=%s",
                declared,
                actual,
            )
            return False
        return True

    def ingest_one(self, artifact_path: Path) -> dict[str, Any] | None:
        """Ingest a single artifact file.

        Returns result dict or None if rejected.

        Result dict::

            {
                "artifact_id": str,       # SHA-256 hex (content-addressed)
                "permalink": str,         # /artifacts/{id} URL
                "event_id": str | None,
                "filename": str,
                "size_bytes": int,
                "distributed_to": list[str],
            }
        """
        if artifact_path.suffix not in SUPPORTED_EXTENSIONS:
            logger.debug("Skipping unsupported extension: %s", artifact_path.name)
            return None

        content = artifact_path.read_bytes()
        meta = self._load_meta(artifact_path)

        # Integrity check (if sha256 declared in sidecar)
        if not self._verify_integrity(content, meta):
            self._reject(artifact_path, "SHA-256 integrity check failed")
            return None

        # Event ID resolution
        event_id = self._extract_event_id(artifact_path, meta)
        if self._require_event_id and not event_id:
            self._reject(
                artifact_path,
                "No event_id found. Provide a .meta.json sidecar with {'event_id': '...'} or name the file with prefix evt-{id}_{filename}",
            )
            return None

        # Detect content type
        suffix = artifact_path.suffix.lower()
        content_type = {
            ".html": "text/html",
            ".md": "text/markdown",
            ".json": "application/json",
            ".txt": "text/plain",
            ".pdf": "application/pdf",
        }.get(suffix, "application/octet-stream")

        source = meta.get("source", "deerflow:research")

        # Store (idempotent — same content → same ID)
        record = self._store.store(
            content=content,
            filename=artifact_path.name,
            content_type=content_type,
            source=source,
            event_id=event_id,
        )

        permalink = self._store.get_permalink(record.id, self._base_url)

        # Distribute (best-effort)
        distributed_to: list[str] = []
        if self._distributor:
            distributed_to = self._distributor.distribute(record, permalink)

        # Move to processed
        processed_path = self._processed_dir / artifact_path.name
        artifact_path.rename(processed_path)
        sidecar = artifact_path.with_suffix(".meta.json")
        if sidecar.exists():
            sidecar.rename(self._processed_dir / sidecar.name)

        logger.info(
            "Ingested artifact %s → id=%s event_id=%s distributed_to=%s",
            artifact_path.name,
            record.id,
            event_id,
            distributed_to,
        )

        return {
            "artifact_id": record.id,
            "permalink": permalink,
            "event_id": event_id,
            "filename": artifact_path.name,
            "size_bytes": record.size_bytes,
            "distributed_to": distributed_to,
        }

    def scan_once(self) -> list[dict[str, Any]]:
        """Scan sandbox directory once and ingest all new artifacts.

        Returns list of result dicts for successfully ingested artifacts.
        """
        results = []
        for path in sorted(self._sandbox_dir.iterdir()):
            if not path.is_file():
                continue
            if path.suffix == ".json" and path.stem.endswith(".meta"):
                continue  # skip sidecar files
            result = self.ingest_one(path)
            if result:
                results.append(result)
        return results

    def run_forever(self) -> None:
        """Poll sandbox directory on interval until stopped."""
        self.setup()
        self._running = True
        logger.info(
            "DeerflowResearchProducer watching %s every %ds",
            self._sandbox_dir,
            self._poll_interval,
        )
        while self._running:
            try:
                results = self.scan_once()
                if results:
                    logger.info("Ingested %d artifact(s) this cycle", len(results))
            except Exception:
                logger.exception("Error in DeerflowResearchProducer scan cycle")
            time.sleep(self._poll_interval)

    def stop(self) -> None:
        """Signal the run_forever loop to stop."""
        self._running = False
