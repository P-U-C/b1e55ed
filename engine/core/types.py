"""engine.core.types

Lightweight dataclasses for hot-path objects.

Pydantic models own IO boundaries; dataclasses keep runtime lean.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class ConvictionScore:
    node_id: str
    symbol: str
    direction: str  # long|short|neutral
    magnitude: float  # 0-10
    timeframe: str
    ts: datetime
    commitment_hash: str
    pcs_score: float | None = None
    cts_score: float | None = None
    regime: str | None = None
    domains_used: list[str] = field(default_factory=list)
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class TradeIntent:
    symbol: str
    direction: str  # long|short
    size_pct: float
    leverage: float
    conviction_score: float
    regime: str
    rationale: str
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None


@dataclass(frozen=True, slots=True)
class RegimeState:
    regime: str
    ts: datetime
    evidence: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FeatureSnapshot:
    cycle_id: str
    symbol: str
    ts: datetime
    features: dict[str, dict[str, float]]
    source_event_ids: list[str] = field(default_factory=list)
    regime: str | None = None
    version: str = "v1"


class ProducerHealth(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    STALE = "stale"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ProducerResult:
    events_published: int
    errors: list[str]
    duration_ms: int
    timestamp: datetime
    staleness_ms: int | None = None
    health: ProducerHealth = ProducerHealth.OK


# ---------------------------------------------------------------------------
# Learning loop dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OutcomeAttribution:
    position_id: str
    conviction_id: int
    realized_pnl: float
    direction_correct: bool
    time_held_hours: float
    max_drawdown_pct: float
    regime_at_entry: str
    domain_scores_at_entry: dict[str, float]


@dataclass(frozen=True, slots=True)
class WeightAdjustment:
    previous_weights: dict[str, float]
    new_weights: dict[str, float]
    deltas: dict[str, float]
    observations: int
    window_days: int
    applied: bool
    reason: str  # "adjusted" | "insufficient_data" | "reverted"


@dataclass(frozen=True, slots=True)
class ProducerScore:
    name: str
    accuracy: float
    total_signals: int
    correct_signals: int
    staleness_avg_ms: float
    error_rate: float


@dataclass(frozen=True, slots=True)
class CorpusFeedback:
    patterns_scored: int
    skills_promoted: list[str]
    skills_archived: list[str]


@dataclass(frozen=True, slots=True)
class LearningResult:
    outcome_attributions: list[OutcomeAttribution]
    weight_adjustment: WeightAdjustment
    producer_scores: dict[str, ProducerScore]
    corpus_feedback: CorpusFeedback
    cycle_timestamp: datetime
