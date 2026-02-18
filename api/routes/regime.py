from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends

from api.auth import AuthDep
from api.deps import get_db
from engine.core.database import Database

router = APIRouter(prefix="/regime", dependencies=[AuthDep])


def _parse_dt(ts: str | None) -> datetime | None:
    if not ts:
        return None
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


@router.get("")
def get_regime(db: Database = Depends(get_db)) -> dict[str, Any]:
    row = db.conn.execute(
        "SELECT payload, ts FROM events WHERE type = ? ORDER BY ts DESC LIMIT 1",
        ("brain.regime_change.v1",),
    ).fetchone()
    if row is None:
        return {"regime": None, "changed_at": None, "conditions": {}}

    payload = json.loads(str(row[0]))
    # RegimeDetector emits payload {'regime': ..., 'confidence':..., 'conditions':...} (best-effort)
    regime = payload.get("regime") or payload.get("state") or payload.get("name")
    conditions = payload.get("conditions") or {}
    return {"regime": regime, "changed_at": _parse_dt(str(row[1])), "conditions": conditions}
