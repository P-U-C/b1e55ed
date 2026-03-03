"""engine.core.events

The event contract is the primitive.

A note from prehistory:
- Hashcash (1997) predates Bitcoin.
- The genesis block (2009) embedded a headline. A system can remember *why* it exists.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

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


from typing import Any, Literal

from pydantic import BaseModel, Field, TypeAdapter, model_validator


class EventType(StrEnum):
    """Canonical event type registry.

    Naming: ``{category}.{domain}.{version}``.
    """

    # Signal events (producers)
    SIGNAL_TA_V1 = "signal.ta.v1"
    SIGNAL_ONCHAIN_V1 = "signal.onchain.v1"
    SIGNAL_TRADFI_V1 = "signal.tradfi.v1"
    SIGNAL_SOCIAL_V1 = "signal.social.v1"
    SIGNAL_SENTIMENT_V1 = "signal.sentiment.v1"
    SIGNAL_EVENTS_V1 = "signal.events.v1"
    SIGNAL_ETF_V1 = "signal.etf.v1"
    SIGNAL_STABLECOIN_V1 = "signal.stablecoin.v1"
    SIGNAL_WHALE_V1 = "signal.whale.v1"
    SIGNAL_ORDERBOOK_V1 = "signal.orderbook.v1"
    SIGNAL_CURATOR_V1 = "signal.curator.v1"
    SIGNAL_ACI_V1 = "signal.aci.v1"
    SIGNAL_PRICE_ALERT_V1 = "signal.price_alert.v1"
    SIGNAL_PRICE_WS_V1 = "signal.price_ws.v1"
    SIGNAL_BENCHMARK_V1 = "signal.benchmark.v1"

    # Brain events
    BRAIN_CYCLE_V1 = "brain.cycle.v1"
    CONVICTION_V1 = "brain.conviction.v1"
    SYNTHESIS_V1 = "brain.synthesis.v1"
    REGIME_CHANGE_V1 = "brain.regime_change.v1"
    FEATURE_SNAPSHOT_V1 = "brain.feature_snapshot.v1"

    # Execution events
    TRADE_INTENT_V1 = "execution.trade_intent.v1"
    ORDER_SUBMITTED_V1 = "execution.order_submitted.v1"
    ORDER_FILLED_V1 = "execution.order_filled.v1"
    ORDER_CANCELED_V1 = "execution.order_canceled.v1"
    ORDER_FAILED_V1 = "execution.order_failed.v1"
    POSITION_OPENED_V1 = "execution.position_opened.v1"
    POSITION_CLOSED_V1 = "execution.position_closed.v1"
    POSITION_UPDATED_V1 = "execution.position_updated.v1"

    # Kill switch
    KILL_SWITCH_V1 = "system.kill_switch.v1"

    # Karma
    KARMA_INTENT_V1 = "karma.intent.v1"
    KARMA_SETTLEMENT_V1 = "karma.settlement.v1"
    KARMA_RECEIPT_V1 = "karma.receipt.v1"
    KARMA_WALLET_MIGRATION_V1 = "karma.wallet_migration.v1"

    # Learning
    LEARNING_OUTCOME_V1 = "learning.outcome.v1"
    LEARNING_WEIGHT_ADJ_V1 = "learning.weight_adjustment.v1"
    LEARNING_REPORT_V1 = "learning.report.v1"

    # Attribution audit
    SIGNAL_ACCEPTED_V1 = "attribution.signal_accepted.v1"

    # Forecast events (producers → brain)
    FORECAST_V1 = "forecast.v1"

    ATTRIBUTION_OUTCOME_V1 = "attribution.outcome.v1"

    # System
    BALANCE_UPDATED_V1 = "system.balance_updated.v1"
    AUDIT_V1 = "system.audit.v1"


class AbstentionReason(StrEnum):
    """Why a producer issued no_forecast this cycle."""

    INSUFFICIENT_DATA = "insufficient_data"
    LOW_CONFIDENCE = "low_confidence"
    REGIME_MISMATCH = "regime_mismatch"
    CONFLICT_UNRESOLVED = "conflict_unresolved"
    THESIS_UNCHANGED = "thesis_unchanged"


class ForecastLifecycleState(StrEnum):
    NEW = "new"
    SUPERSEDE = "supersede"
    REAFFIRM = "reaffirm"
    REVOKE = "revoke"


# -----------------
# Typed payloads
# -----------------


class TASignalPayload(BaseModel):
    """Payload for :pydata:`~engine.core.events.EventType.SIGNAL_TA_V1`."""

    symbol: str
    rsi_14: float | None = None
    ema_20: float | None = None
    ema_50: float | None = None
    ema_200: float | None = None
    bb_position: float | None = None
    volume_ratio: float | None = None
    trend: Literal["bullish", "bearish", "neutral"] | None = None
    trend_strength: float | None = None
    support_distance: float | None = None
    resistance_distance: float | None = None


class OnchainSignalPayload(BaseModel):
    symbol: str
    whale_netflow: float | None = None
    exchange_flow: float | None = None
    active_addresses_change: float | None = None
    price_momentum_24h: float | None = None


class TradFiSignalPayload(BaseModel):
    symbol: str
    basis_annualized: float | None = None
    funding_annualized: float | None = None
    oi_change_pct: float | None = None
    meltup_score: float | None = None
    direction: str | None = None
    confidence: float | None = None
    horizon: str = "swing"
    invalidation: float | None = None
    signal_reason: str | None = None


class SocialSignalPayload(BaseModel):
    symbol: str
    score: float
    direction: Literal["bullish", "bearish", "neutral"]
    source_count: int
    contrarian_flag: bool = False
    echo_chamber_flag: bool = False


class SentimentSignalPayload(BaseModel):
    symbol: str
    fear_greed: float | None = None
    fear_greed_change_7d: float | None = None
    ct_sentiment: str | None = None


class EventsSignalPayload(BaseModel):
    symbol: str
    headline_sentiment: float | None = None
    impact_score: float | None = None
    event_count: int = 0
    catalysts: list[str] = Field(default_factory=list)


class ETFFlowPayload(BaseModel):
    symbol: str
    daily_flow_usd: float | None = None
    streak_days: int = 0
    cumulative_7d: float | None = None


class StablecoinSignalPayload(BaseModel):
    stablecoin: str
    supply_change_24h: float | None = None
    supply_change_7d: float | None = None
    mint_burn_events: int = 0


class WhaleSignalPayload(BaseModel):
    symbol: str
    smart_money_netflow: float | None = None
    top_holders_change: float | None = None


class OrderbookSignalPayload(BaseModel):
    symbol: str
    bid_depth_usd: float | None = None
    ask_depth_usd: float | None = None
    imbalance: float | None = None
    lod_score: float | None = None


class PriceWSSignalPayload(BaseModel):
    """Payload for :pydata:`~engine.core.events.EventType.SIGNAL_PRICE_WS_V1`.

    Polling placeholder for a future websocket feed.
    """

    symbol: str
    price: float | None = None
    bid: float | None = None
    ask: float | None = None
    venue: str | None = None


class BenchmarkSignalPayload(BaseModel):
    """Payload for benchmark signal producers."""

    symbol: str
    direction: Literal["long", "short", "flat"]
    confidence: float
    source: str
    reasoning: str | None = None


class CuratorSignalPayload(BaseModel):
    symbol: str
    direction: Literal["bullish", "bearish", "neutral"]
    conviction: float
    rationale: str
    source: str = "operator"


class ACISignalPayload(BaseModel):
    symbol: str
    consensus_score: float
    models_queried: int
    models_responded: int
    dispersion: float


class ConvictionPayload(BaseModel):
    symbol: str
    direction: Literal["long", "short", "neutral"]
    magnitude: float
    timeframe: str
    pcs_score: float
    cts_score: float | None = None
    regime: str
    domains_used: list[str]
    commitment_hash: str


class TradeIntentPayload(BaseModel):
    symbol: str
    direction: Literal["long", "short"]
    size_pct: float
    leverage: float
    conviction_score: float
    regime: str
    rationale: str
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None


class KarmaIntentPayload(BaseModel):
    trade_id: str
    realized_pnl_usd: float
    karma_percentage: float
    karma_amount_usd: float
    node_id: str


class KillSwitchPayload(BaseModel):
    level: int
    previous_level: int
    reason: str
    auto: bool
    actor: str = "system"


class LearningOutcomePayload(BaseModel):
    position_id: str
    symbol: str
    direction: Literal["long", "short"]
    realized_pnl: float
    realized_pnl_pct: float
    time_held_hours: float
    conviction_at_entry: float
    regime_at_entry: str
    max_drawdown_during: float
    signals_at_entry: dict[str, float]


class WeightAdjustmentPayload(BaseModel):
    cycle_type: Literal["daily", "weekly", "monthly"]
    adjustments: dict[str, dict[str, float]]
    reason: str
    observations: int
    approved: bool = False


class SignalAcceptedPayload(BaseModel):
    """Payload for SIGNAL_ACCEPTED_V1 — links a trade to a contributing signal."""

    trade_id: str
    producer_id: str
    domain: str
    signal_event_id: str
    contribution_weight: float = 1.0
    direction: str
    confidence: float
    horizon: str | None = None
    invalidation: float | None = None


class ProducerOutcome(BaseModel):
    """Single producer's outcome within an attribution event."""

    producer_id: str
    domain: str
    contribution_weight: float
    outcome: float  # +1.0 win, -1.0 loss, 0.0 neutral
    karma_delta: float


class AttributionOutcomePayload(BaseModel):
    """Payload for ATTRIBUTION_OUTCOME_V1 — emitted when position closes."""

    trade_id: str
    realized_pnl_usd: float
    confidence_bucket: Literal["high", "mid", "low"]
    producers: list[ProducerOutcome]


class ForecastPayload(BaseModel):
    """Payload for FORECAST_V1 — the producer's probabilistic call.

    Immutable after emission. Lifecycle changes (supersede/revoke/reaffirm)
    are new events, not updates to existing ones.
    """

    forecast_id: str  # uuid4 — immutable after emission
    protocol_version: str = "1.0"
    asset: str  # BTC | ETH | SOL | etc.
    horizon: str  # "1h" | "4h" | "24h"
    action: Literal["long", "short", "flat", "no_forecast"]
    confidence: float = Field(ge=0.0, le=1.0)  # P(positive EV | regime, net fees); 0.0–1.0
    calibrated: bool = False  # True only after 50+ resolved forecasts
    invalidation: float | None = None  # price that kills thesis; None when no_forecast
    regime_tag: str = "unknown"  # risk-on | risk-off | chop | unknown
    crisis_state: bool = False  # execution override, separate from regime_tag
    reasoning_hash: str | None = None  # sha256(candidate_forecast + llm_critique + rationale)
    source: str  # producer_name@version
    lifecycle_state: ForecastLifecycleState = ForecastLifecycleState.NEW
    supersedes_forecast_id: str | None = None  # populated when lifecycle=supersede|revoke
    visible_signal_refs: list[str] = Field(default_factory=list)  # ALL event_ids in lookback window
    used_signal_refs: list[str] = Field(default_factory=list)  # event_ids that materially informed call
    abstention_reason: AbstentionReason | None = None  # set when action=no_forecast

    @model_validator(mode="after")
    def validate_no_forecast_abstention(self) -> ForecastPayload:
        if self.action == "no_forecast" and self.abstention_reason is None:
            raise ValueError("abstention_reason is required when action='no_forecast'")
        return self


PayloadModel = (
    TASignalPayload
    | OnchainSignalPayload
    | TradFiSignalPayload
    | SocialSignalPayload
    | SentimentSignalPayload
    | EventsSignalPayload
    | ETFFlowPayload
    | StablecoinSignalPayload
    | WhaleSignalPayload
    | OrderbookSignalPayload
    | BenchmarkSignalPayload
    | CuratorSignalPayload
    | ACISignalPayload
    | ConvictionPayload
    | TradeIntentPayload
    | KarmaIntentPayload
    | KillSwitchPayload
    | LearningOutcomePayload
    | WeightAdjustmentPayload
    | SignalAcceptedPayload
    | AttributionOutcomePayload
    | ForecastPayload
)


_EVENT_PAYLOAD_MODELS: dict[EventType, type[BaseModel]] = {
    EventType.SIGNAL_TA_V1: TASignalPayload,
    EventType.SIGNAL_ONCHAIN_V1: OnchainSignalPayload,
    EventType.SIGNAL_TRADFI_V1: TradFiSignalPayload,
    EventType.SIGNAL_SOCIAL_V1: SocialSignalPayload,
    EventType.SIGNAL_SENTIMENT_V1: SentimentSignalPayload,
    EventType.SIGNAL_EVENTS_V1: EventsSignalPayload,
    EventType.SIGNAL_ETF_V1: ETFFlowPayload,
    EventType.SIGNAL_STABLECOIN_V1: StablecoinSignalPayload,
    EventType.SIGNAL_WHALE_V1: WhaleSignalPayload,
    EventType.SIGNAL_ORDERBOOK_V1: OrderbookSignalPayload,
    EventType.SIGNAL_BENCHMARK_V1: BenchmarkSignalPayload,
    EventType.SIGNAL_CURATOR_V1: CuratorSignalPayload,
    EventType.SIGNAL_ACI_V1: ACISignalPayload,
    # Brain
    EventType.CONVICTION_V1: ConvictionPayload,
    EventType.TRADE_INTENT_V1: TradeIntentPayload,
    # Karma
    EventType.KARMA_INTENT_V1: KarmaIntentPayload,
    # Kill switch
    EventType.KILL_SWITCH_V1: KillSwitchPayload,
    # Learning
    EventType.LEARNING_OUTCOME_V1: LearningOutcomePayload,
    EventType.LEARNING_WEIGHT_ADJ_V1: WeightAdjustmentPayload,
    # Attribution
    EventType.SIGNAL_ACCEPTED_V1: SignalAcceptedPayload,
    # Forecast
    EventType.FORECAST_V1: ForecastPayload,
    EventType.ATTRIBUTION_OUTCOME_V1: AttributionOutcomePayload,
}


def payload_model_for(event_type: EventType) -> type[BaseModel] | None:
    return _EVENT_PAYLOAD_MODELS.get(event_type)


def canonical_json(data: Any) -> str:
    """Canonical JSON serialization used for hashing and dedupe."""

    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def payload_hash(payload: BaseModel | dict[str, Any]) -> str:
    """SHA-256 hash of canonical payload JSON."""

    obj = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def compute_dedupe_key(event_type: EventType, payload: BaseModel | dict[str, Any]) -> str:
    """Dedup key format: ``{event_type}:{sha256(canonical_payload)}``."""

    return f"{event_type}:{payload_hash(payload)}"


class EventEnvelope(BaseModel):
    """Canonical event envelope.

    This is the stable interface across producers, brain, execution, and learning.
    """

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


_event_envelope_adapter = TypeAdapter(EventEnvelope)


def validate_envelope(obj: Any) -> EventEnvelope:
    """Validate (and normalize) an event envelope."""

    return _event_envelope_adapter.validate_python(obj)
