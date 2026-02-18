"""engine.execution.pnl

Minimal P&L helpers used by Sprint 2B tests.

(Full tracker arrives in the complete Phase 2 build; this is the core primitive.)
"""

from __future__ import annotations


def realized_pnl_usd(*, direction: str, entry_price: float, exit_price: float, size_notional: float) -> float:
    if size_notional < 0:
        raise ValueError("size_notional must be >= 0")
    if direction not in {"long", "short"}:
        raise ValueError("direction must be 'long' or 'short'")

    if direction == "long":
        return (exit_price - entry_price) * (size_notional / entry_price)
    # short
    return (entry_price - exit_price) * (size_notional / entry_price)
