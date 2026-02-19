from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class BrainStatus(BaseModel):
    regime: str | None = None
    regime_changed_at: datetime | None = None
    kill_switch_level: int = 0
    kill_switch_reason: str | None = None
    kill_switch_changed_at: datetime | None = None
    last_cycle_id: str | None = None
    last_cycle_at: datetime | None = None


class CycleResult(BaseModel):
    cycle_id: str
    ts: datetime
    intents: list[dict[str, Any]] = []
    regime: str | None = None
    kill_switch_level: int | None = None
