from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.deps import get_db
from engine import __version__
from engine.core.database import Database

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: float
    db_size_bytes: int
    db: dict[str, Any]
    brain: dict[str, Any]
    kill_switch: dict[str, Any]


@router.get("/health")
def health(request: Request, db: Database = Depends(get_db)) -> JSONResponse:
    started_at = float(getattr(request.app.state, "started_at", time.monotonic()))
    uptime = time.monotonic() - started_at

    db_path = Path(getattr(db, "db_path", ""))
    db_size = 0
    if db_path and db_path.exists():
        try:
            db_size = os.path.getsize(db_path)
        except OSError:
            db_size = 0

    # 1. DB connectivity test
    try:
        db.execute("SELECT 1").fetchone()
        db_ok = True
        db_error = None
    except Exception as e:  # noqa: BLE001
        db_ok = False
        db_error = str(e)

    # 2. Last brain cycle recency
    cycle_age_minutes = None
    try:
        last_cycle = db.execute("SELECT ts FROM events WHERE type = 'brain.cycle.v1' ORDER BY ts DESC LIMIT 1").fetchone()
        if last_cycle:
            from datetime import datetime

            try:
                from datetime import UTC  # py311+
            except ImportError:  # pragma: no cover
                from datetime import timezone as _tz  # noqa: PLC0415

                UTC = _tz.utc  # noqa: N806, UP017

            last_ts = datetime.fromisoformat(str(last_cycle[0]).replace("Z", "+00:00"))
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=UTC)
            cycle_age_minutes = (datetime.now(UTC) - last_ts).total_seconds() / 60
    except Exception:  # noqa: BLE001
        pass

    # 3. Kill switch state
    kill_switch_level = 0
    try:
        ks_row = db.execute("SELECT payload FROM events WHERE type = 'system.kill_switch.v1' ORDER BY ts DESC LIMIT 1").fetchone()
        if ks_row:
            ks = json.loads(ks_row[0])
            kill_switch_level = int(ks.get("level", 0))
    except Exception:  # noqa: BLE001
        pass

    payload: dict[str, Any] = {
        "status": "ok" if db_ok else "degraded",
        "version": __version__,
        "uptime_seconds": uptime,
        "db_size_bytes": db_size,
        "db": {"ok": db_ok, "error": db_error},
        "brain": {"last_cycle_age_minutes": cycle_age_minutes},
        "kill_switch": {"level": kill_switch_level},
    }

    status_code = 200 if db_ok else 503
    return JSONResponse(content=payload, status_code=status_code)
