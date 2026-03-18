"""SPI internal data models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AcceptedSignal:
    """Canonical signal record — same shape whether from adapter or gateway."""

    signal_id: str  # uuid assigned by accept_signal()
    signal_client_id: str  # producer-provided idempotency key
    submission_id: str  # submission this signal came from
    producer_id: str  # registered producer
    ingress_mode: str  # "adapter" or "native"
    symbol: str
    direction: str  # "bullish" | "bearish" | "neutral"
    confidence: float  # [0.55, 0.99]
    horizon_hours: int
    submitted_at: str  # ISO timestamp
    attribution_window_start: str
    attribution_window_end: str
    status: str = "accepted"
    event_id: str | None = None  # native b1e55ed event_id (from emit_observation)
    signal_payload_json: str | None = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class SignalOutcome:
    """Resolved outcome for an accepted signal."""

    outcome_id: str
    signal_id: str
    producer_id: str
    resolved_at: str
    status: str  # "resolved" | "expired" | "invalidated"
    outcome_label: str | None  # "correct" | "incorrect" | None
    direction_correct: bool | None
    entry_price: float | None
    exit_price: float | None
    price_change_pct: float | None
    resolution_method: str | None
    brier_component: float | None
    karma_delta: float | None
    score_delta: float | None
    chain_hash: str | None = None
    event_id: str | None = None


@dataclass
class ProducerKarmaState:
    """Current karma state for a producer."""

    producer_id: str
    epoch: int
    epoch_brier: float | None
    epoch_karma: float | None
    running_karma: float
    resolved_count: int
    updated_at: str
