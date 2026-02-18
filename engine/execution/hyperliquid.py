"""engine.execution.hyperliquid

Hyperliquid execution adapter.

This module provides a small, testable boundary for order placement.
In production we can swap the underlying implementation (SDK vs HTTP) without
changing callers.

The unit tests in Sprint 2B rely on an injected API object.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class HLOrder:
    id: str
    symbol: str
    side: str  # "buy" | "sell"
    size: float
    price: float | None
    status: str  # "open" | "filled" | "canceled" | "rejected"
    filled_price: float | None = None


class HyperliquidApi(Protocol):
    def place_order(
        self, *, symbol: str, side: str, size: float, price: float | None = None
    ) -> HLOrder: ...

    def cancel_order(self, *, order_id: str) -> bool: ...

    def get_order(self, *, order_id: str) -> HLOrder | None: ...


class HyperliquidAdapter:
    """Thin adapter that delegates to an injected API implementation."""

    def __init__(self, *, api: HyperliquidApi) -> None:
        self._api = api

    def place(
        self, *, symbol: str, side: str, size: float, price: float | None = None
    ) -> HLOrder:
        sym = str(symbol).upper().strip()
        if side not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'")
        if size <= 0:
            raise ValueError("size must be > 0")
        return self._api.place_order(symbol=sym, side=side, size=float(size), price=price)

    def cancel(self, *, order_id: str) -> bool:
        return bool(self._api.cancel_order(order_id=str(order_id)))

    def status(self, *, order_id: str) -> HLOrder | None:
        return self._api.get_order(order_id=str(order_id))


class InMemoryHyperliquidApi:
    """Test-double API: minimal in-memory orderbook."""

    def __init__(self) -> None:
        self._orders: dict[str, HLOrder] = {}

    def place_order(
        self, *, symbol: str, side: str, size: float, price: float | None = None
    ) -> HLOrder:
        oid = str(uuid.uuid4())
        o = HLOrder(id=oid, symbol=symbol, side=side, size=float(size), price=price, status="open")
        self._orders[oid] = o
        return o

    def cancel_order(self, *, order_id: str) -> bool:
        o = self._orders.get(order_id)
        if o is None:
            return False
        if o.status == "filled":
            return False
        self._orders[order_id] = HLOrder(
            id=o.id,
            symbol=o.symbol,
            side=o.side,
            size=o.size,
            price=o.price,
            status="canceled",
            filled_price=o.filled_price,
        )
        return True

    def get_order(self, *, order_id: str) -> HLOrder | None:
        return self._orders.get(order_id)

    def fill_order(self, *, order_id: str, fill_price: float) -> HLOrder:
        o = self._orders[order_id]
        self._orders[order_id] = HLOrder(
            id=o.id,
            symbol=o.symbol,
            side=o.side,
            size=o.size,
            price=o.price,
            status="filled",
            filled_price=float(fill_price),
        )
        return self._orders[order_id]
