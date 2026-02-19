from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from api.deps import get_db
from engine import __version__
from engine.core.database import Database

router = APIRouter()


class HealthResponse(BaseModel):
    version: str
    uptime_seconds: float
    db_size_bytes: int


@router.get("/health", response_model=HealthResponse)
def health(request: Request, db: Database = Depends(get_db)) -> HealthResponse:
    started_at = float(getattr(request.app.state, "started_at", time.monotonic()))
    uptime = time.monotonic() - started_at

    db_path = Path(getattr(db, "db_path", ""))
    db_size = 0
    if db_path and db_path.exists():
        try:
            db_size = os.path.getsize(db_path)
        except OSError:
            db_size = 0

    return HealthResponse(
        version=__version__,
        uptime_seconds=uptime,
        db_size_bytes=db_size,
    )
