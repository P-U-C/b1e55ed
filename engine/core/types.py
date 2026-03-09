"""engine.core.types

Lightweight dataclasses for hot-path objects.

Pydantic models own IO boundaries; dataclasses keep runtime lean.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

try:
    from enum import StrEnum  # py311+
except ImportError:  # pragma: no cover
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]  # noqa: UP042
        """Backport of Python 3.11's enum.StrEnum for Python 3.10.

        Key behavior: str(member) should equal member.value.
        """

        def __str__(self) -> str:  # pragma: no cover
            return str(self.value)

        def __format__(self, spec: str) -> str:  # pragma: no cover
            return format(str(self), spec)


# Linnaeus proposed six ranks -- kingdom, class, order, genus, species, variety.
# Six domains. Exhaustive, non-overlapping. Any addition requires a new system.
CANONICAL_DOMAINS: Final[frozenset[str]] = frozenset(
    {
        "technical",
        "onchain",
        "tradfi",
        "social",
        "events",
        "curator",
    }
)
"""Canonical 6 producer domains.

Rules:
- ``curator`` is a human-input/override channel — never rename to macro.
- ``macro`` becomes the 7th domain only when a dedicated macro producer ships.
- ACI → social. Stablecoin → onchain. Price alerts → technical.
- Any producer with a domain not in this set will raise at initialisation.
"""


# Phil Karlton's two hard problems: cache invalidation and naming things.
# This function is the second problem, resolved by constraint.
def validate_domain(domain: str) -> str:
    """Validate a domain string against CANONICAL_DOMAINS. Returns domain if valid."""
    if domain not in CANONICAL_DOMAINS:
        raise ValueError(f"Invalid producer domain '{domain}'. Must be one of: {sorted(CANONICAL_DOMAINS)}")
    return domain


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
    horizon: str | None = None
    invalidation: float | None = None


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
    horizon: str | None = None
    invalidation: float | None = None
    source_event_ids: list[str] = field(default_factory=list)
    intended_price: float | None = None
    conviction_id: int | None = None  # Links to conviction_scores.id for outcome attribution


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
