"""engine.execution.oms

Order Management System (OMS) — minimal implementation for Phase 2 Sprint 2B.

The OMS is the boundary between intent and execution.
In paper mode, it routes to PaperAdapter.
On close, it records realized P&L and triggers Karma intent (fail-open).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from engine.core.config import Config
from engine.core.database import Database
from engine.execution.karma import KarmaEngine
from engine.execution.paper import PaperAdapter
from engine.execution.pnl import realized_pnl_usd
from engine.execution.preflight import Preflight


@dataclass(frozen=True)
class TradeIntent:
    symbol: str
    direction: str  # "long" | "short"
    size_notional: float
    leverage: float = 1.0


@dataclass(frozen=True)
class ExecutionResult:
    trade_id: str
    position_id: str
    entry_price: float


class OMS:
    def __init__(
        self,
        *,
        config: Config,
        db: Database,
        paper: PaperAdapter,
        preflight: Preflight,
        karma: KarmaEngine,
    ) -> None:
        self._config = config
        self._db = db
        self._paper = paper
        self._preflight = preflight
        self._karma = karma

    def submit(self, *, intent: TradeIntent, entry_price: float) -> ExecutionResult:
        pf = self._preflight.check(
            mode=self._config.execution.mode, symbol=intent.symbol, size_notional=intent.size_notional
        )
        if not pf.ok:
            raise ValueError(f"preflight_failed:{pf.reason}")

        trade_id = str(uuid.uuid4())
        fill = self._paper.open_position(
            asset=intent.symbol,
            direction=intent.direction,
            entry_price=float(entry_price),
            size_notional=float(intent.size_notional),
            leverage=float(intent.leverage),
        )
        return ExecutionResult(
            trade_id=trade_id,
            position_id=fill.position_id,
            entry_price=float(entry_price),
        )

    def close(self, *, trade_id: str, position_id: str, exit_price: float) -> float:
        row = self._db.conn.execute(
            "SELECT direction, entry_price, size_notional FROM positions WHERE id = ?",
            (str(position_id),),
        ).fetchone()
        if row is None:
            raise KeyError("position_not_found")

        direction = str(row[0])
        entry = float(row[1])
        size = float(row[2])
        pnl = realized_pnl_usd(direction=direction, entry_price=entry, exit_price=float(exit_price), size_notional=size)

        self._paper.close_position(position_id=str(position_id), exit_price=float(exit_price), realized_pnl=pnl)

        # Fail-open karma intent.
        self._karma.record_intent(trade_id=str(trade_id), realized_pnl_usd=pnl)

        return pnl
