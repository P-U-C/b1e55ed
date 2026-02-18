from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends

from api.auth import AuthDep
from api.deps import get_db, get_registry
from engine.core.database import Database

router = APIRouter(prefix="/producers", dependencies=[AuthDep])


def _parse_dt(ts: str | None) -> datetime | None:
    if not ts:
        return None
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


@router.get("/status")
def producer_status(
    db: Database = Depends(get_db),
    registry=Depends(get_registry),
) -> dict[str, Any]:
    names = registry.list_producers()
    out: dict[str, Any] = {}

    for name in names:
        row = db.conn.execute(
            """
            SELECT name, domain, schedule, last_run_at, last_success_at, last_error,
                   consecutive_failures, events_produced, avg_duration_ms, expected_interval_ms, updated_at
            FROM producer_health
            WHERE name = ?
            """,
            (name,),
        ).fetchone()

        if row is None:
            out[name] = {
                "name": name,
                "domain": getattr(registry.get_producer(name), "domain", None),
                "healthy": None,
                "last_run_at": None,
                "last_success_at": None,
                "last_error": None,
                "consecutive_failures": 0,
                "events_produced": 0,
            }
            continue

        consecutive_failures = int(row[6]) if row[6] is not None else 0
        last_error = str(row[5]) if row[5] is not None else None
        healthy = consecutive_failures == 0 and last_error is None

        out[name] = {
            "name": str(row[0]),
            "domain": str(row[1]) if row[1] is not None else None,
            "schedule": str(row[2]) if row[2] is not None else None,
            "healthy": healthy,
            "last_run_at": _parse_dt(str(row[3])) if row[3] is not None else None,
            "last_success_at": _parse_dt(str(row[4])) if row[4] is not None else None,
            "last_error": last_error,
            "consecutive_failures": consecutive_failures,
            "events_produced": int(row[7]) if row[7] is not None else 0,
            "avg_duration_ms": float(row[8]) if row[8] is not None else None,
            "expected_interval_ms": int(row[9]) if row[9] is not None else None,
            "updated_at": _parse_dt(str(row[10])) if row[10] is not None else None,
        }

    return {"producers": out}
