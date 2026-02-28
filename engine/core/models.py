"""engine.core.models

Core domain models.

The event envelope is immutable. The system's memory is append-only.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from pydantic import BaseModel

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
    hash_version: int = 1  # v2 includes contributor_id in the hash

    model_config = {"frozen": True}


def compute_event_hash(
    *,
    prev_hash: str | None,
    event_type: EventType,
    payload: dict[str, Any],
    ts: datetime,
    source: str | None = None,
    trace_id: str | None = None,
    schema_version: str = "v1",
    dedupe_key: str | None = None,
    event_id: str,
    contributor_id: str | None = None,
    hash_version: int = 1,
) -> str:
    """Compute the canonical SHA-256 event hash.

    Commits to the full event header, not just payload.

    hash_version=1 (legacy):
        Hash = sha256(prev_hash | ts | event_id | type | schema_version |
                      source | trace_id | dedupe_key | canonical_payload_json)

    hash_version=2 (current):
        Appends contributor_id to the hash input, making attribution tamper-evident.
        Hash = sha256(prev_hash | ts | event_id | type | schema_version |
                      source | trace_id | dedupe_key | contributor_id |
                      canonical_payload_json)

    All fields are deterministic and tamper-evident.
    """

    # Canonical header fields (deterministic order)
    header_parts = [
        prev_hash or "",
        ts.isoformat(),
        event_id,
        getattr(event_type, "value", str(event_type)),
        schema_version,
        source or "",
        trace_id or "",
        dedupe_key or "",
    ]

    # v2+: include contributor_id in the hash so attribution is tamper-evident.
    if hash_version >= 2:
        header_parts.append(contributor_id or "")

    data = "|".join(header_parts) + "|" + canonical_json(payload)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()
