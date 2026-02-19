from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query

from api.auth import AuthDep
from api.deps import get_db
from api.schemas.common import PaginatedResponse
from api.schemas.signals import SignalResponse
from engine.core.database import Database

router = APIRouter(prefix="/signals", dependencies=[AuthDep])


def _parse_dt(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


@router.get("", response_model=PaginatedResponse[SignalResponse])
def list_signals(
    db: Database = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    domain: str | None = Query(None, description="Filter by domain (ta/onchain/tradfi/social/etc)"),
) -> PaginatedResponse[SignalResponse]:
    like = "signal.%"
    if domain:
        like = f"signal.{domain}.%"

    total_row = db.conn.execute(
        "SELECT COUNT(1) FROM events WHERE type LIKE ?",
        (like,),
    ).fetchone()
    total = int(total_row[0]) if total_row is not None else 0

    rows = db.conn.execute(
        """
        SELECT id, type, ts, source, payload
        FROM events
        WHERE type LIKE ?
        ORDER BY ts DESC
        LIMIT ? OFFSET ?
        """,
        (like, limit, offset),
    ).fetchall()

    items: list[SignalResponse] = []
    import json

    for r in rows:
        items.append(
            SignalResponse(
                id=str(r[0]),
                type=str(r[1]),
                ts=_parse_dt(str(r[2])),
                source=str(r[3]) if r[3] is not None else None,
                payload=json.loads(str(r[4])) if r[4] is not None else {},
            )
        )

    return PaginatedResponse(items=items, limit=limit, offset=offset, total=total)
