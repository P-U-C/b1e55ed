"""api.routes.trace

Stateful Trace Sessions — lets an operator tag a sequence of actions as one
logical trace.

Sessions are stored in brain.db (table: trace_sessions) and expire after 24 h
if not accessed.

Endpoints:
  POST /api/v1/trace/session              — create a new session
  PUT  /api/v1/trace/session/{id}/append  — append a trace_id to the session
  GET  /api/v1/trace/session/{id}         — retrieve session + linked events
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.auth import AuthDep
from api.deps import get_db
from api.errors import B1e55edError
from engine.core.database import Database

router = APIRouter(prefix="/trace", tags=["trace"], dependencies=[AuthDep])

SESSION_TTL_HOURS = 24


# ---------------------------------------------------------------------------
# Schema migration helper
# ---------------------------------------------------------------------------


def _ensure_trace_sessions_table(db: Database) -> None:
    db.conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trace_sessions (
            session_id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_accessed_at TEXT NOT NULL,
            trace_ids TEXT NOT NULL DEFAULT '[]'
        )
        """
    )
    db.conn.execute("CREATE INDEX IF NOT EXISTS idx_trace_sessions_label ON trace_sessions(label)")
    db.conn.commit()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=255, description="Human-readable label for the session")


class CreateSessionResponse(BaseModel):
    session_id: str
    label: str
    created_at: str
    trace_ids: list[str]


class AppendTraceRequest(BaseModel):
    trace_id: str = Field(..., min_length=1, description="Trace ID to append to the session")


class TraceEvent(BaseModel):
    id: str
    type: str
    ts: str
    source: str | None
    trace_id: str
    payload: dict[str, Any]


class SessionDetailResponse(BaseModel):
    session_id: str
    label: str
    created_at: str
    last_accessed_at: str
    trace_ids: list[str]
    events: list[TraceEvent]
    expired: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_expired(last_accessed_at: str) -> bool:
    try:
        dt = datetime.fromisoformat(last_accessed_at.replace("Z", "+00:00"))
        return datetime.now(tz=UTC) > dt + timedelta(hours=SESSION_TTL_HOURS)
    except Exception:
        return False


def _touch_session(db: Database, session_id: str) -> None:
    now = datetime.now(tz=UTC).isoformat()
    with db.conn:
        db.conn.execute(
            "UPDATE trace_sessions SET last_accessed_at = ? WHERE session_id = ?",
            (now, session_id),
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/session", response_model=CreateSessionResponse, status_code=201)
def create_session(
    body: CreateSessionRequest,
    db: Database = Depends(get_db),
) -> CreateSessionResponse:
    """Create a new stateful trace session."""
    _ensure_trace_sessions_table(db)

    session_id = str(uuid.uuid4())
    now = datetime.now(tz=UTC).isoformat()

    with db.conn:
        db.conn.execute(
            """
            INSERT INTO trace_sessions (session_id, label, created_at, last_accessed_at, trace_ids)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, body.label, now, now, json.dumps([])),
        )

    return CreateSessionResponse(
        session_id=session_id,
        label=body.label,
        created_at=now,
        trace_ids=[],
    )


@router.put("/session/{session_id}/append", response_model=CreateSessionResponse)
def append_trace(
    session_id: str,
    body: AppendTraceRequest,
    db: Database = Depends(get_db),
) -> CreateSessionResponse:
    """Append a trace_id to an existing session."""
    _ensure_trace_sessions_table(db)

    row = db.conn.execute(
        "SELECT label, created_at, last_accessed_at, trace_ids FROM trace_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()

    if row is None:
        raise B1e55edError(
            code="trace.session_not_found",
            message="Trace session not found",
            status=404,
            session_id=session_id,
        )

    label = str(row[0])
    created_at = str(row[1])
    last_accessed_at = str(row[2])
    trace_ids: list[str] = json.loads(str(row[3]))

    if _is_expired(last_accessed_at):
        raise B1e55edError(
            code="trace.session_expired",
            message="Trace session has expired (24 h TTL)",
            status=410,
            session_id=session_id,
        )

    if body.trace_id not in trace_ids:
        trace_ids.append(body.trace_id)

    now = datetime.now(tz=UTC).isoformat()
    with db.conn:
        db.conn.execute(
            "UPDATE trace_sessions SET trace_ids = ?, last_accessed_at = ? WHERE session_id = ?",
            (json.dumps(trace_ids), now, session_id),
        )

    return CreateSessionResponse(
        session_id=session_id,
        label=label,
        created_at=created_at,
        trace_ids=trace_ids,
    )


@router.get("/session/{session_id}", response_model=SessionDetailResponse)
def get_session(
    session_id: str,
    db: Database = Depends(get_db),
) -> SessionDetailResponse:
    """Retrieve a trace session including all linked events."""
    _ensure_trace_sessions_table(db)

    row = db.conn.execute(
        "SELECT label, created_at, last_accessed_at, trace_ids FROM trace_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()

    if row is None:
        raise B1e55edError(
            code="trace.session_not_found",
            message="Trace session not found",
            status=404,
            session_id=session_id,
        )

    label = str(row[0])
    created_at = str(row[1])
    last_accessed_at = str(row[2])
    trace_ids: list[str] = json.loads(str(row[3]))
    expired = _is_expired(last_accessed_at)

    # Fetch all events whose trace_id is in the session's trace_id list
    events: list[TraceEvent] = []
    if trace_ids and not expired:
        placeholders = ",".join("?" * len(trace_ids))
        event_rows = db.conn.execute(
            f"""
            SELECT id, type, ts, source, trace_id, payload
            FROM events
            WHERE trace_id IN ({placeholders})
            ORDER BY ts ASC
            """,
            trace_ids,
        ).fetchall()

        for er in event_rows:
            events.append(
                TraceEvent(
                    id=str(er[0]),
                    type=str(er[1]),
                    ts=str(er[2]),
                    source=str(er[3]) if er[3] is not None else None,
                    trace_id=str(er[4]),
                    payload=json.loads(str(er[5])),
                )
            )

    # Touch to refresh TTL on read
    if not expired:
        _touch_session(db, session_id)
        last_accessed_at = datetime.now(tz=UTC).isoformat()

    return SessionDetailResponse(
        session_id=session_id,
        label=label,
        created_at=created_at,
        last_accessed_at=last_accessed_at,
        trace_ids=trace_ids,
        events=events,
        expired=expired,
    )
