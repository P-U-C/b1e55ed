from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.auth_kill_switch import KillSwitchAuthDep
from api.deps import get_db, get_kill_switch
from engine.brain.kill_switch import KillSwitch, KillSwitchLevel
from engine.core.database import Database
from engine.core.kill_switch_alerts import notify_kill_switch_escalated, notify_kill_switch_reset

router = APIRouter(prefix="/kill-switch", tags=["brain"])


class KillSwitchSetRequest(BaseModel):
    level: int = Field(..., ge=0, le=4)
    reason: str = Field("manual", description="Human readable reason")


@router.get("/status")
def status(ks: KillSwitch = Depends(get_kill_switch)) -> dict:
    return {"level": int(ks.level)}


@router.post("/set", dependencies=[KillSwitchAuthDep])
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

    if level > prev:
        level_name = KillSwitchLevel(level).name
        notify_kill_switch_escalated(
            previous_level=prev,
            level=level,
            level_name=level_name,
            reason=str(payload.reason),
        )
    elif level < prev:
        notify_kill_switch_reset(previous_level=prev, level=level, actor="api")

    import contextlib

    with contextlib.suppress(Exception):
        ks.reset(level=level)

    return {"status": "ok", "event_id": ev.id, "level": level}
