"""engine.core.models

Core domain models.

The event envelope is immutable. The system's memory is append-only.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from engine.core.events import EventType, canonical_json


class Event(BaseModel):
    """Immutable event record. The system's fundamental primitive."""

    id: str
    type: EventType
    ts: datetime
    observed_at: datetime | None = None
    source: str | None = None
    trace_id: str | None = None
    schema_version: str = "v1"
    dedupe_key: str | None = None
    payload: dict[str, Any]
    prev_hash: str | None = None
    hash: str

    model_config = {"frozen": True}


def compute_event_hash(*, prev_hash: str | None, event_type: EventType, payload: dict[str, Any]) -> str:
    """Compute the canonical SHA-256 event hash.

    Hash = sha256((prev_hash or '') + '|' + type + '|' + canonical_payload_json)
    """

    data = (prev_hash or "") + "|" + str(event_type) + "|" + canonical_json(payload)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()
