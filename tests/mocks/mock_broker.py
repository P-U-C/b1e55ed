"""tests.mocks.mock_broker

MockBroker — in-memory OMS/broker for test assertions.

Features:
- Records all orders placed (symbol, side, size, price, timestamp)
- Simulates immediate fills at requested price
- Configurable slippage and partial fills
- Configurable order rejection (for preflight testing)
- Exposes filled_orders, open_positions, closed_positions for assertions
- Can wrap the real PaperBroker or operate standalone
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

try:
    from datetime import UTC
except ImportError:

    UTC = UTC


# ──────────────────────────────────────────────────────────────────────────────
# Data types
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class MockOrder:
    order_id: str
    position_id: str
    symbol: str
    side: str  # buy | sell
    size: float  # units
    price: float  # fill price
    notional_usd: float
    fee_usd: float
    status: str  # filled | rejected | partial
    timestamp: datetime
    slippage_bps: float = 0.0
    partial_fill_pct: float = 1.0  # 1.0 = full fill
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def filled_size(self) -> float:
        return self.size * self.partial_fill_pct


@dataclass
class MockPosition:
    position_id: str
    symbol: str
    direction: str  # long | short
    entry_price: float
    size_notional: float
    stop_loss: float | None
    take_profit: float | None
    opened_at: datetime
    closed_at: datetime | None = None
    exit_price: float | None = None
    realized_pnl: float | None = None
    status: str = "open"  # open | closed

    def unrealized_pnl(self, mark_price: float) -> float:
        qty = self.size_notional / self.entry_price if self.entry_price > 0 else 0.0
        if self.direction == "long":
            return (mark_price - self.entry_price) * qty
        return (self.entry_price - mark_price) * qty

    def close(self, exit_price: float, *, ts: datetime | None = None) -> float:
        qty = self.size_notional / self.entry_price if self.entry_price > 0 else 0.0
        if self.direction == "long":
            pnl = (exit_price - self.entry_price) * qty
        else:
            pnl = (self.entry_price - exit_price) * qty
        self.exit_price = exit_price
        self.realized_pnl = pnl
        self.status = "closed"
        self.closed_at = ts or datetime.now(tz=UTC)
        return pnl


# ──────────────────────────────────────────────────────────────────────────────
# Mock broker config
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class MockBrokerConfig:
    slippage_bps: float = 0.0  # basis points of slippage on fills
    partial_fill_pct: float = 1.0  # 1.0 = full fill, 0.5 = 50% fill
    reject_next_n: int = 0  # reject the next N orders
    fee_rate: float = 0.0006  # 0.06% fee
    rejection_reason: str = "mock_rejection"


# ──────────────────────────────────────────────────────────────────────────────
# MockBroker
# ──────────────────────────────────────────────────────────────────────────────


class MockBroker:
    """Pure in-memory broker for unit/integration testing.

    Can be used standalone (no real DB) or as an assertion layer alongside
    the real PaperBroker.
    """

    def __init__(self, config: MockBrokerConfig | None = None):
        self._cfg = config or MockBrokerConfig()
        self._orders: list[MockOrder] = []
        self._positions: dict[str, MockPosition] = {}  # position_id → MockPosition
        self._reject_counter = self._cfg.reject_next_n

    # ── Configuration helpers ─────────────────────────────────────────────────

    def configure(self, **kwargs: Any) -> None:
        """Update broker config at runtime (for scenario setup)."""
        for k, v in kwargs.items():
            setattr(self._cfg, k, v)
        if "reject_next_n" in kwargs:
            self._reject_counter = int(kwargs["reject_next_n"])

    def reset(self) -> None:
        """Clear all state — useful between scenarios."""
        self._orders.clear()
        self._positions.clear()
        self._reject_counter = self._cfg.reject_next_n

    # ── Core order execution ──────────────────────────────────────────────────

    def execute_market(
        self,
        *,
        symbol: str,
        direction: str,  # long | short
        notional_usd: float,
        mid_price: float,
        leverage: float = 1.0,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MockOrder:
        """Place a market order. Returns immediately with fill or rejection."""
        sym = str(symbol).upper().strip()
        dirn = str(direction).lower()
        if dirn not in {"long", "short"}:
            raise ValueError(f"direction must be long|short, got {dirn!r}")
        side = "buy" if dirn == "long" else "sell"

        # Rejection gate
        if self._reject_counter > 0:
            self._reject_counter -= 1
            order = MockOrder(
                order_id=idempotency_key or str(uuid.uuid4()),
                position_id=str(uuid.uuid4()),
                symbol=sym,
                side=side,
                size=0.0,
                price=mid_price,
                notional_usd=notional_usd,
                fee_usd=0.0,
                status="rejected",
                timestamp=datetime.now(tz=UTC),
                metadata={"reason": self._cfg.rejection_reason, **(metadata or {})},
            )
            self._orders.append(order)
            return order

        # Slippage
        slip = self._cfg.slippage_bps / 10_000.0
        fill_price = mid_price * (1.0 + slip) if side == "buy" else mid_price * (1.0 - slip)

        # Partial fill
        actual_notional = notional_usd * self._cfg.partial_fill_pct
        fill_size = actual_notional / fill_price if fill_price > 0 else 0.0
        fee = actual_notional * self._cfg.fee_rate

        order_id = idempotency_key or str(uuid.uuid4())
        position_id = str(uuid.uuid4())
        ts = datetime.now(tz=UTC)

        order = MockOrder(
            order_id=order_id,
            position_id=position_id,
            symbol=sym,
            side=side,
            size=fill_size,
            price=fill_price,
            notional_usd=actual_notional,
            fee_usd=fee,
            status="filled" if self._cfg.partial_fill_pct >= 1.0 else "partial",
            timestamp=ts,
            slippage_bps=self._cfg.slippage_bps,
            partial_fill_pct=self._cfg.partial_fill_pct,
            metadata=metadata or {},
        )
        self._orders.append(order)

        # Track position
        position = MockPosition(
            position_id=position_id,
            symbol=sym,
            direction=dirn,
            entry_price=fill_price,
            size_notional=actual_notional,
            stop_loss=stop_loss,
            take_profit=take_profit,
            opened_at=ts,
        )
        self._positions[position_id] = position

        return order

    def close_position(
        self,
        position_id: str,
        *,
        exit_price: float,
        reason: str = "",
    ) -> float:
        """Close an open position. Returns realized P&L."""
        pos = self._positions.get(position_id)
        if pos is None:
            raise ValueError(f"Position {position_id!r} not found")
        if pos.status != "open":
            raise ValueError(f"Position {position_id!r} is already {pos.status}")
        return pos.close(exit_price)

    _PRICE_EPS = 1e-8  # tolerance for floating-point price comparisons

    def check_stops_and_targets(self, mark_prices: dict[str, float]) -> list[tuple[str, str, float]]:
        """Scan open positions against current mark prices.

        Returns a list of (position_id, reason, exit_price) for positions that
        should be closed due to stop-loss or take-profit triggers.

        Uses a small epsilon for floating-point safe comparisons so that
        prices like 198.00000000000003 match a trigger at exactly 198.0.
        """
        triggers: list[tuple[str, str, float]] = []
        eps = self._PRICE_EPS
        for pos_id, pos in self._positions.items():
            if pos.status != "open":
                continue
            mark = mark_prices.get(pos.symbol)
            if mark is None:
                continue

            if pos.direction == "long":
                if pos.stop_loss is not None and mark <= pos.stop_loss + eps:
                    triggers.append((pos_id, "stop_loss", pos.stop_loss))
                elif pos.take_profit is not None and mark >= pos.take_profit - eps:
                    triggers.append((pos_id, "take_profit", pos.take_profit))
            else:  # short
                if pos.stop_loss is not None and mark >= pos.stop_loss - eps:
                    triggers.append((pos_id, "stop_loss", pos.stop_loss))
                elif pos.take_profit is not None and mark <= pos.take_profit + eps:
                    triggers.append((pos_id, "take_profit", pos.take_profit))

        return triggers

    def process_triggers(self, mark_prices: dict[str, float]) -> list[tuple[str, str, float]]:
        """Check triggers and auto-close triggered positions. Returns closed positions."""
        triggered = self.check_stops_and_targets(mark_prices)
        closed = []
        for pos_id, reason, exit_price in triggered:
            pnl = self.close_position(pos_id, exit_price=exit_price, reason=reason)
            closed.append((pos_id, reason, pnl))
        return closed

    # ── Assertions interface ──────────────────────────────────────────────────

    @property
    def filled_orders(self) -> list[MockOrder]:
        return [o for o in self._orders if o.status == "filled"]

    @property
    def rejected_orders(self) -> list[MockOrder]:
        return [o for o in self._orders if o.status == "rejected"]

    @property
    def partial_orders(self) -> list[MockOrder]:
        return [o for o in self._orders if o.status == "partial"]

    @property
    def open_positions(self) -> list[MockPosition]:
        return [p for p in self._positions.values() if p.status == "open"]

    @property
    def closed_positions(self) -> list[MockPosition]:
        return [p for p in self._positions.values() if p.status == "closed"]

    @property
    def all_positions(self) -> list[MockPosition]:
        return list(self._positions.values())

    def get_position(self, position_id: str) -> MockPosition | None:
        return self._positions.get(position_id)

    def positions_for_symbol(self, symbol: str) -> list[MockPosition]:
        sym = symbol.upper()
        return [p for p in self._positions.values() if p.symbol == sym]

    def open_positions_for_symbol(self, symbol: str) -> list[MockPosition]:
        sym = symbol.upper()
        return [p for p in self._positions.values() if p.symbol == sym and p.status == "open"]

    def total_realized_pnl(self) -> float:
        return sum(p.realized_pnl or 0.0 for p in self.closed_positions)

    def has_open_position_for(self, symbol: str) -> bool:
        return len(self.open_positions_for_symbol(symbol)) > 0

    def summary(self) -> dict[str, Any]:
        return {
            "filled_orders": len(self.filled_orders),
            "rejected_orders": len(self.rejected_orders),
            "partial_orders": len(self.partial_orders),
            "open_positions": len(self.open_positions),
            "closed_positions": len(self.closed_positions),
            "total_realized_pnl": self.total_realized_pnl(),
        }
