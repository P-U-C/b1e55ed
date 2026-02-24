"""api.routes.events

SSE event stream endpoint.

Streams brain.db events to clients in Server-Sent Events format.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from starlette.requests import Request
from starlette.responses import StreamingResponse

from api.auth import AuthDep
from api.deps import get_db
from engine.core.database import Database

router = APIRouter(prefix="/events", dependencies=[AuthDep])


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def _row_to_sse_json(row: object) -> str:
    """Convert a DB row (sqlite3.Row) to an SSE JSON string."""
    import json as _json

    payload_raw = row["payload"]  # type: ignore[index]
    try:
        payload = _json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw
    except Exception:
        payload = {}

    ts_raw = row["ts"]  # type: ignore[index]
    try:
        from engine.core.database import _iso_to_dt

        ts_dt = _iso_to_dt(str(ts_raw))
        ts_str = _iso(ts_dt) if ts_dt else str(ts_raw)
    except Exception:
        ts_str = str(ts_raw) if ts_raw else ""

    obj = {
        "id": str(row["id"]),  # type: ignore[index]
        "type": str(row["type"]),  # type: ignore[index]
        "ts": ts_str,
        "payload": payload,
    }
    return json.dumps(obj)


async def _event_generator(
    request: Request,
    db: Database,
    since_ts: float | None,
    type_filter: list[str] | None,
) -> AsyncIterator[str]:
    """Async generator that yields SSE-formatted strings."""

    # Build type filter fragment
    def _type_clause(alias: str = "") -> tuple[str, list[object]]:
        prefix = f"{alias}." if alias else ""
        if not type_filter:
            return "", []
        placeholders = ",".join("?" * len(type_filter))
        return f" AND {prefix}type IN ({placeholders})", list(type_filter)

    # --- 1. Stream historical events (since provided) ---
    last_id: str | None = None

    if since_ts is not None:
        since_dt = datetime.fromtimestamp(since_ts, tz=UTC)
        since_iso = _iso(since_dt)

        type_frag, type_params = _type_clause()
        q = f"SELECT id, type, ts, payload FROM events WHERE ts >= ?{type_frag} ORDER BY ts ASC, rowid ASC"
        params: list[object] = [since_iso, *type_params]

        rows = db.conn.execute(q, params).fetchall()
        for row in rows:
            if await request.is_disconnected():
                return
            data = _row_to_sse_json(row)
            last_id = str(row["id"])
            yield f"data: {data}\n\n"

    # --- 2. Poll for new events every 2s ---
    # Track the latest rowid we have delivered
    if last_id is not None:
        row_cur = db.conn.execute("SELECT rowid FROM events WHERE id = ?", (last_id,)).fetchone()
        last_rowid: int = int(row_cur[0]) if row_cur else 0
    else:
        # Start from the current tail
        row_tail = db.conn.execute("SELECT MAX(rowid) FROM events").fetchone()
        last_rowid = int(row_tail[0]) if row_tail and row_tail[0] is not None else 0

    while True:
        if await request.is_disconnected():
            return

        type_frag, type_params = _type_clause()
        q = f"SELECT id, type, ts, payload, rowid FROM events WHERE rowid > ?{type_frag} ORDER BY rowid ASC"
        params2: list[object] = [last_rowid, *type_params]
        rows = db.conn.execute(q, params2).fetchall()

        for row in rows:
            if await request.is_disconnected():
                return
            data = _row_to_sse_json(row)
            last_rowid = int(row["rowid"])
            yield f"data: {data}\n\n"

        await asyncio.sleep(2.0)


@router.get("/stream")
async def stream_events(
    request: Request,
    since: float | None = Query(None, description="Unix timestamp — stream events from this point"),
    types: str | None = Query(None, description="Comma-separated event type filter, e.g. brain.decision,brain.signal"),
    db: Database = Depends(get_db),
) -> StreamingResponse:
    """Stream brain.db events as Server-Sent Events (SSE).

    - ``since``: optional Unix timestamp; historical events from that point are sent first.
    - ``types``: optional comma-separated list of event types to include.

    Each SSE payload is a JSON object with fields: ``id``, ``type``, ``ts``, ``payload``.
    """
    type_filter: list[str] | None = None
    if types:
        type_filter = [t.strip() for t in types.split(",") if t.strip()]

    gen = _event_generator(request, db, since, type_filter)

    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
