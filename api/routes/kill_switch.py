from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.auth_kill_switch import KillSwitchAuthDep
from api.deps import get_db, get_kill_switch
from api.errors import B1e55edError
from engine.brain.kill_switch import KillSwitch
from engine.core.database import Database

router = APIRouter(prefix="/kill-switch", dependencies=[KillSwitchAuthDep], tags=["brain"])


class KillSwitchSetRequest(BaseModel):
    level: int = Field(..., ge=0, le=4)
    reason: str = Field("manual", description="Human readable reason")


@router.get("/status")
def status(ks: KillSwitch = Depends(get_kill_switch)) -> dict:
    return {"level": int(ks.level)}


@router.post("/set")
def set_level(
    payload: KillSwitchSetRequest,
    db: Database = Depends(get_db),
    ks: KillSwitch = Depends(get_kill_switch),
) -> dict:
    level = int(payload.level)

    # Persist as an event; KillSwitch will rehydrate from event store.
    from engine.core.events import EventType

    prev = int(ks.level)
    ev = db.append_event(
        event_type=EventType.KILL_SWITCH_V1,
        payload={
            "level": level,
            "previous_level": prev,
            "reason": str(payload.reason),
            "auto": False,
            "actor": "api",
        },
        source="api.kill_switch",
    )

    import contextlib

    with contextlib.suppress(Exception):
        ks.reset(level=level)

    if level < 0 or level > 4:
        raise B1e55edError(code="kill_switch.invalid_level", message="Level must be 0-4", status=400)

    return {"status": "ok", "event_id": ev.id, "level": level}
