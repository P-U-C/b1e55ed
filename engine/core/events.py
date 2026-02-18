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
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, TypeAdapter


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

    # Learning
    LEARNING_OUTCOME_V1 = "learning.outcome.v1"
    LEARNING_WEIGHT_ADJ_V1 = "learning.weight_adjustment.v1"
    LEARNING_REPORT_V1 = "learning.report.v1"

    # System
    BALANCE_UPDATED_V1 = "system.balance_updated.v1"
    AUDIT_V1 = "system.audit.v1"


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
    | CuratorSignalPayload
    | ACISignalPayload
    | ConvictionPayload
    | TradeIntentPayload
    | KarmaIntentPayload
    | KillSwitchPayload
    | LearningOutcomePayload
    | WeightAdjustmentPayload
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
