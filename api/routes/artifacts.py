"""api.routes.artifacts

Artifact storage and retrieval endpoints.

DeerFlow generates artifacts (HTML briefs, research reports) into the sandbox.
These endpoints ingest, store, and serve them with content-addressed permalinks.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response

from api.auth import AuthDep
from api.deps import get_db
from engine.artifacts.store import ArtifactStore
from engine.core.database import Database

router = APIRouter(prefix="/artifacts", dependencies=[AuthDep])


def _get_store(db: Database = Depends(get_db)) -> ArtifactStore:
    return ArtifactStore(db=db)


def _base_url() -> str:
    return os.getenv("B1E55ED_API_BASE_URL", "http://localhost:5050/api/v1")


# ------------------------------------------------------------------
# GET /artifacts/ — List recent artifacts
# ------------------------------------------------------------------


@router.get("/")
def list_artifacts(
    limit: int = Query(default=20, ge=1, le=100),
    store: ArtifactStore = Depends(_get_store),
) -> dict[str, Any]:
    items = store.list_recent(limit=limit)
    base = _base_url()
    return {
        "items": [
            {
                "id": a.id,
                "filename": a.filename,
                "content_type": a.content_type,
                "size_bytes": a.size_bytes,
                "created_at": a.created_at,
                "source": a.source,
                "event_id": a.event_id,
                "permalink": store.get_permalink(a.id, base),
            }
            for a in items
        ],
        "total": len(items),
    }


# ------------------------------------------------------------------
# GET /artifacts/{artifact_id} — Serve artifact content
# ------------------------------------------------------------------


@router.get("/{artifact_id}")
def get_artifact(
    artifact_id: str,
    store: ArtifactStore = Depends(_get_store),
) -> Response:
    record = store.get(artifact_id)
    if record is None:
        return JSONResponse(
            {"error": "artifact_not_found", "message": f"No artifact with id {artifact_id}"},
            status_code=404,
        )

    file_path = Path(record.storage_path)
    if not file_path.exists():
        return JSONResponse(
            {"error": "artifact_file_missing", "message": "Artifact record exists but file is missing"},
            status_code=404,
        )

    content = file_path.read_bytes()
    return Response(
        content=content,
        media_type=record.content_type,
        headers={
            "Content-Disposition": f'inline; filename="{record.filename}"',
            "X-Artifact-Id": record.id,
        },
    )


# ------------------------------------------------------------------
# GET /artifacts/{artifact_id}/meta — Metadata JSON
# ------------------------------------------------------------------


@router.get("/{artifact_id}/meta")
def get_artifact_meta(
    artifact_id: str,
    store: ArtifactStore = Depends(_get_store),
) -> Response:
    record = store.get(artifact_id)
    if record is None:
        return JSONResponse(
            {"error": "artifact_not_found", "message": f"No artifact with id {artifact_id}"},
            status_code=404,
        )

    base = _base_url()
    return JSONResponse(
        {
            "id": record.id,
            "filename": record.filename,
            "content_type": record.content_type,
            "size_bytes": record.size_bytes,
            "created_at": record.created_at,
            "source": record.source,
            "event_id": record.event_id,
            "permalink": store.get_permalink(record.id, base),
        }
    )


# ------------------------------------------------------------------
# POST /artifacts/ingest — Ingest artifact from DeerFlow
# ------------------------------------------------------------------


@router.post("/ingest")
def ingest_artifact(
    body: dict[str, Any],
    store: ArtifactStore = Depends(_get_store),
) -> dict[str, Any]:
    content_b64 = body.get("content_base64", "")
    filename = body.get("filename", "unnamed")
    content_type = body.get("content_type", "application/octet-stream")
    source = body.get("source", "deerflow")
    event_id = body.get("event_id")
    require_event_id = body.get("require_event_id", True)

    # DeerFlow artifacts must be linked to a source signal
    if require_event_id and not event_id:
        return JSONResponse(
            {
                "error": "missing_event_id",
                "message": (
                    "Artifacts from DeerFlow must be linked to a source "
                    "signal.research.v1 event. Provide 'event_id' in the "
                    "request body. Pass require_event_id=false to skip "
                    "(non-DeerFlow sources only)."
                ),
            },
            status_code=422,
        )

    content = base64.b64decode(content_b64)

    record = store.store(
        content=content,
        filename=filename,
        content_type=content_type,
        source=source,
        event_id=event_id,
    )

    base = _base_url()
    return {
        "artifact_id": record.id,
        "permalink": store.get_permalink(record.id, base),
        "event_id": event_id,
    }
