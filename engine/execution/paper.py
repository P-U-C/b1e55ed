"""engine.execution.paper

Paper execution adapter.

The paper adapter simulates fills deterministically for tests:
- Orders fill immediately at the provided price.
- Positions are written to the `positions` table.

This is intentionally small: it exists to support the Phase 2 execution pipeline
and tests. It is not a market simulator.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from engine.core.database import Database


@dataclass(frozen=True)
class PaperFill:
    order_id: str
    position_id: str
    fill_price: float
    fill_size_notional: float


class PaperAdapter:
    def __init__(self, *, db: Database, venue: str = "paper") -> None:
        self._db = db
        self._venue = venue

    def open_position(
        self,
        *,
        asset: str,
        direction: str,
        entry_price: float,
        size_notional: float,
        leverage: float = 1.0,
        margin_type: str = "isolated",
    ) -> PaperFill:
        if direction not in {"long", "short"}:
            raise ValueError("direction must be 'long' or 'short'")

        position_id = str(uuid.uuid4())
        order_id = str(uuid.uuid4())
        now = datetime.now(tz=UTC).isoformat()

        with self._db.conn:
            self._db.conn.execute(
                """
                INSERT INTO positions (
                    id, platform, asset, direction, entry_price, size_notional, leverage, margin_type,
                    opened_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
                """,
                (
                    position_id,
                    self._venue,
                    str(asset).upper(),
                    direction,
                    float(entry_price),
                    float(size_notional),
                    float(leverage),
                    str(margin_type),
                    now,
                ),
            )
            self._db.conn.execute(
                """
                INSERT INTO orders (
                    id, position_id, venue, type, side, symbol, size, price, fill_price, fill_size, status,
                    created_at, filled_at
                ) VALUES (?, ?, ?, 'market', ?, ?, ?, ?, ?, ?, 'filled', datetime('now'), datetime('now'))
                """,
                (
                    order_id,
                    position_id,
                    self._venue,
                    "buy" if direction == "long" else "sell",
                    str(asset).upper(),
                    float(size_notional),
                    float(entry_price),
                    float(entry_price),
                    float(size_notional),
                ),
            )

        return PaperFill(
            order_id=order_id,
            position_id=position_id,
            fill_price=float(entry_price),
            fill_size_notional=float(size_notional),
        )

    def close_position(self, *, position_id: str, exit_price: float, realized_pnl: float) -> None:
        now = datetime.now(tz=UTC).isoformat()
        with self._db.conn:
            self._db.conn.execute(
                """
                UPDATE positions
                SET status='closed', closed_at=?, realized_pnl=?
                WHERE id=?
                """,
                (now, float(realized_pnl), str(position_id)),
            )
