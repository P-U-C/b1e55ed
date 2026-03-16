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
        db.fetchone("SELECT 1")
        db_ok = True
        db_error = None
    except Exception as e:  # noqa: BLE001
        db_ok = False
        db_error = str(e)

    # 2. Last brain cycle recency
    cycle_age_minutes = None
    try:
        last_cycle = db.fetchone("SELECT ts FROM events WHERE type = 'brain.cycle.v1' ORDER BY ts DESC LIMIT 1")
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
        ks_row = db.fetchone("SELECT payload FROM events WHERE type = 'system.kill_switch.v1' ORDER BY ts DESC LIMIT 1")
        if ks_row:
            ks = json.loads(ks_row[0])
            kill_switch_level = int(ks.get("level", 0))
    except Exception:  # noqa: BLE001
        pass

    # Determine brain_cycle_status
    stale_threshold_minutes = 30
    if cycle_age_minutes is None:
        brain_cycle_status = "unknown"
    elif cycle_age_minutes > stale_threshold_minutes:
        brain_cycle_status = "stale"
    else:
        brain_cycle_status = "ok"

    # Determine kill_switch status
    kill_switch_active = kill_switch_level > 0

    # Compute overall status: degrade on stale cycle or active kill switch
    if not db_ok or brain_cycle_status == "stale" or kill_switch_active:
        overall_status = "degraded"
    else:
        overall_status = "ok"

    payload: dict[str, Any] = {
        "status": overall_status,
        "version": __version__,
        "uptime_seconds": uptime,
        "db_size_bytes": db_size,
        "db": {"ok": db_ok, "error": db_error},
        "brain": {
            "last_cycle_age_minutes": cycle_age_minutes,
            "cycle_status": brain_cycle_status,
            "stale_threshold_minutes": stale_threshold_minutes,
        },
        "kill_switch": {
            "level": kill_switch_level,
            "active": kill_switch_active,
            **({"status": "active"} if kill_switch_active else {}),
        },
        "brain_cycle_status": brain_cycle_status,
    }

    status_code = 200 if db_ok else 503
    return JSONResponse(content=payload, status_code=status_code)
