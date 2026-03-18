"""External producer data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExternalObservation:
    """Raw observation from an external producer endpoint."""

    symbol: str
    direction: str  # "bullish" | "bearish" | "neutral"
    confidence: float  # 0.0–1.0
    horizon_hours: int  # evaluation horizon in hours
    observed_at: str  # ISO timestamp
    regime: str | None = None
    signal_type: str | None = None
    source_assertion: str | None = None  # e.g. "EXECUTE", "WAIT"
    hit_rate: float | None = None
    avg_return: float | None = None
    is_stale: bool = False
    health_state: str = "HEALTHY"  # "HEALTHY" | "DEGRADED" | "HALT"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawExternalRecord:
    """Pre-normalization record from connector."""

    source_system: str
    source_endpoint: str
    source_payload_hash: str
    adapter_version: str
    raw_payload: dict[str, Any]
    fetched_at: str
