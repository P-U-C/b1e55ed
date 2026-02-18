from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SignalResponse(BaseModel):
    id: str
    type: str
    ts: datetime
    source: str | None = None
    payload: dict[str, Any]
