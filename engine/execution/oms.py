"""engine.execution.oms

Order Management System (OMS).

Responsibilities (Sprint 2A):
- accept TradeIntent
- enforce preflight gates (policy, kill switch, etc.)
- size the position
- route to paper or live broker
- persist canonical state to DB via orders/positions tables and execution events

Modes:
- paper: implemented (PaperBroker)
- live: adapter boundary only (Sprint 2B)

No dry_run mode (DECISIONS_V3 #4).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType, TradeIntentPayload
from engine.core.policy import TradingPolicyEngine
from engine.core.types import TradeIntent
from engine.execution.paper import PaperBroker
from engine.execution.position_sizer import CorrelationAwareSizer, PositionSizer, RiskLimits
from engine.execution.preflight import Preflight


def _utc_now() -> datetime:
    return datetime.now(tz=UTC).replace(microsecond=0)


@dataclass(frozen=True, slots=True)
class OMSResult:
    status: str  # filled|rejected|error
    mode: str
    order_id: str | None = None
    position_id: str | None = None
    notional_usd: float | None = None
    reasons: list[str] | None = None


class OMS:
    def __init__(
        self,
        *,
        config: Config,
        db: Database,
        preflight: Preflight,
        sizer: CorrelationAwareSizer,
        paper_broker: PaperBroker | None = None,
        policy: TradingPolicyEngine | None = None,
    ) -> None:
        self.config = config
        self.db = db
        self.preflight = preflight
        self.sizer = sizer
        self.paper = paper_broker or PaperBroker(db)
        self.policy = policy

    def submit(
        self,
        intent: TradeIntent,
        *,
        mid_price: float,
        equity_usd: float,
        portfolio_heat_pct: float = 0.0,
        corr_to_portfolio: float = 0.0,
        idempotency_key: str | None = None,
        gas_balances: dict[tuple[str, str], float] | None = None,
    ) -> OMSResult:
        mode = str(self.config.execution.mode)
        idem = idempotency_key or str(uuid.uuid4())

        # Record intent event for auditability.
        payload = TradeIntentPayload(
            symbol=intent.symbol,
            direction=intent.direction,
            size_pct=float(intent.size_pct),
            leverage=float(intent.leverage),
            conviction_score=float(intent.conviction_score),
            regime=str(intent.regime),
            rationale=str(intent.rationale),
            stop_loss_pct=float(intent.stop_loss_pct) if intent.stop_loss_pct is not None else None,
            take_profit_pct=float(intent.take_profit_pct) if intent.take_profit_pct is not None else None,
        ).model_dump(mode="json")
        self.db.append_event(
            event_type=EventType.TRADE_INTENT_V1,
            payload=payload,
            source="execution.oms",
            dedupe_key=f"{EventType.TRADE_INTENT_V1}:{idem}",
            ts=_utc_now(),
        )

        pf = self.preflight.check(
            intent,
            mode=mode,
            equity_usd=float(equity_usd),
            gas_balances=gas_balances,
        )
        if not pf.approved:
            return OMSResult(status="rejected", mode=mode, reasons=pf.reasons)

        # Size notional (USD) - ignore intent.size_pct here; sizing uses conviction and caps.
        max_pct = float(self.config.risk.max_position_pct)
        notional = self.sizer.size_usd(
            equity_usd=float(equity_usd),
            conviction_score=max(0.0, min(1.0, float(intent.conviction_score) / 100.0)),
            corr_to_portfolio=float(corr_to_portfolio),
            portfolio_heat_pct=float(portfolio_heat_pct),
            max_position_pct=max_pct,
        )
        if notional <= 0:
            return OMSResult(status="rejected", mode=mode, reasons=["size_zero"])

        stop_loss = None
        take_profit = None
        if intent.stop_loss_pct is not None:
            stop_loss = float(mid_price) * (1.0 - float(intent.stop_loss_pct))
        if intent.take_profit_pct is not None:
            take_profit = float(mid_price) * (1.0 + float(intent.take_profit_pct))

        if mode == "paper":
            fill = self.paper.execute_market(
                symbol=intent.symbol,
                direction=intent.direction,
                notional_usd=float(notional),
                leverage=float(intent.leverage),
                mid_price=float(mid_price),
                stop_loss=stop_loss,
                take_profit=take_profit,
                idempotency_key=idem,
            )

            # Persist execution events as well (redundant with tables, but useful for the event bus).
            self.db.append_event(
                event_type=EventType.ORDER_SUBMITTED_V1,
                payload={
                    "order_id": fill.order_id,
                    "position_id": fill.position_id,
                    "venue": "paper",
                    "type": "market",
                    "side": fill.side,
                    "symbol": fill.symbol,
                    "size": float(fill.fill_size),
                    "idempotency_key": idem,
                },
                source="execution.oms",
            )
            self.db.append_event(
                event_type=EventType.ORDER_FILLED_V1,
                payload={
                    "order_id": fill.order_id,
                    "position_id": fill.position_id,
                    "fill_price": float(fill.fill_price),
                    "fill_size": float(fill.fill_size),
                    "fee_usd": float(fill.fee_usd),
                },
                source="execution.oms",
            )
            self.db.append_event(
                event_type=EventType.POSITION_OPENED_V1,
                payload={
                    "position_id": fill.position_id,
                    "platform": "paper",
                    "asset": fill.symbol,
                    "direction": intent.direction,
                    "entry_price": float(fill.fill_price),
                    "size_notional": float(fill.notional_usd),
                    "leverage": float(intent.leverage),
                },
                source="execution.oms",
            )

            return OMSResult(
                status="filled",
                mode=mode,
                order_id=fill.order_id,
                position_id=fill.position_id,
                notional_usd=float(notional),
            )

        if mode == "live":
            raise NotImplementedError("live execution adapter not implemented in Sprint 2A")

        return OMSResult(status="error", mode=mode, reasons=[f"unknown_mode:{mode}"])


def default_sizer_from_config(cfg: Config) -> CorrelationAwareSizer:
    base = PositionSizer(
        kelly=None,
        limits=RiskLimits(max_position_pct=float(cfg.risk.max_position_pct), min_position_usd=10.0),
    )
    return CorrelationAwareSizer(base)
