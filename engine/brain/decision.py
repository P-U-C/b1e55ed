"""engine.brain.decision

Decision engine: PCS × Regime → action.

This module ports the legacy decision matrix concept but adapts it to v3:
- emits `execution.trade_intent.v1` intents
- kill switch gates any action
- approval flow exists for high-conviction trades (represented as a flag in rationale)

"Conviction over consensus" is not a slogan here; it is a policy surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType
from engine.core.types import TradeIntent

from engine.brain.kill_switch import KillSwitchLevel


@dataclass(frozen=True, slots=True)
class DecisionContext:
    symbol: str
    pcs: float
    regime: str
    kill_level: KillSwitchLevel


@runtime_checkable
class DecisionPolicy(Protocol):
    def decide(self, ctx: DecisionContext) -> TradeIntent | None: ...


class DefaultDecisionPolicy:
    """A small, deterministic matrix.

    The matrix is intentionally simple for v1.0. Policy is swappable.
    """

    def __init__(self, config: Config):
        self.config = config

    def decide(self, ctx: DecisionContext) -> TradeIntent | None:
        if ctx.kill_level >= KillSwitchLevel.DEFENSIVE:
            return None

        # Crisis: no new risk.
        if ctx.regime == "CRISIS":
            return None

        # Direction from PCS around 50.
        direction = "long" if ctx.pcs >= 55.0 else "short" if ctx.pcs <= 45.0 else "long"

        # Sizing tiers.
        if ctx.pcs >= 90.0:
            size_pct = 0.10
            leverage = min(2.0, self.config.risk.max_leverage)
            rationale = "approval_required: high conviction over consensus"
        elif ctx.pcs >= 75.0:
            size_pct = 0.05
            leverage = min(2.0, self.config.risk.max_leverage)
            rationale = "enter: strong conviction"
        elif ctx.pcs >= 60.0:
            size_pct = 0.02
            leverage = 1.0
            rationale = "enter: moderate conviction"
        else:
            return None

        size_pct = min(size_pct, self.config.risk.max_position_pct)

        return TradeIntent(
            symbol=ctx.symbol,
            direction=direction,
            size_pct=float(size_pct),
            leverage=float(leverage),
            conviction_score=float(ctx.pcs),
            regime=str(ctx.regime),
            rationale=rationale,
            stop_loss_pct=0.05,
            take_profit_pct=0.10,
        )


class DecisionEngine:
    def __init__(
        self,
        config: Config,
        db: Database,
        *,
        policy: DecisionPolicy | None = None,
    ):
        self.config = config
        self.db = db
        self.policy = policy or DefaultDecisionPolicy(config)

    def decide_and_emit(
        self,
        *,
        symbol: str,
        pcs: float,
        regime: str,
        kill_level: KillSwitchLevel,
        source: str = "brain.decision",
        trace_id: str | None = None,
    ) -> TradeIntent | None:
        ctx = DecisionContext(symbol=str(symbol).upper(), pcs=float(pcs), regime=str(regime), kill_level=kill_level)
        intent = self.policy.decide(ctx)
        if intent is None:
            return None

        payload = {
            "symbol": intent.symbol,
            "direction": intent.direction,
            "size_pct": intent.size_pct,
            "leverage": intent.leverage,
            "conviction_score": intent.conviction_score,
            "regime": intent.regime,
            "rationale": intent.rationale,
            "stop_loss_pct": intent.stop_loss_pct,
            "take_profit_pct": intent.take_profit_pct,
        }
        self.db.append_event(event_type=EventType.TRADE_INTENT_V1, payload=payload, source=source, trace_id=trace_id)
        return intent
