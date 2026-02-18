"""engine.execution.paper

Paper trading adapter.

Requirements (Sprint 2A):
- simulated fills
- position tracking
- persist to the new DB schema (positions, orders)

This is intentionally minimal. It fills immediately at the provided mid price with
configurable slippage + fee.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from engine.core.database import Database


def _utc_now() -> datetime:
    return datetime.now(tz=UTC).replace(microsecond=0)


@dataclass(frozen=True, slots=True)
class PaperConfig:
    slippage_bps: float = 5.0
    fee_rate: float = 0.0006
    platform: str = "paper"
    venue: str = "paper"


@dataclass(frozen=True, slots=True)
class PaperFill:
    order_id: str
    position_id: str
    symbol: str
    side: str  # buy|sell
    fill_price: float
    fill_size: float
    notional_usd: float
    fee_usd: float
    realized_pnl_usd: float | None


class PaperBroker:
    """Writes orders + positions into the shared DB."""

    def __init__(self, db: Database, *, config: PaperConfig | None = None) -> None:
        self.db = db
        self.cfg = config or PaperConfig()

    def _fill_price(self, *, mid: float, side: str) -> float:
        slip = float(self.cfg.slippage_bps) / 10_000.0
        if side == "buy":
            return float(mid) * (1.0 + slip)
        return float(mid) * (1.0 - slip)

    def _existing_open_position(self, symbol: str) -> dict[str, Any] | None:
        row = self.db.conn.execute(
            "SELECT * FROM positions WHERE asset = ? AND status = 'open' ORDER BY opened_at DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        return None if row is None else dict(row)

    def execute_market(
        self,
        *,
        symbol: str,
        direction: str,
        notional_usd: float,
        leverage: float = 1.0,
        mid_price: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PaperFill:
        sym = str(symbol).upper().strip()
        dirn = str(direction).lower().strip()
        if dirn not in {"long", "short"}:
            raise ValueError("direction must be 'long' or 'short'")

        mid = float(mid_price)
        if mid <= 0:
            raise ValueError("mid_price must be > 0")

        n_usd = float(notional_usd)
        if n_usd <= 0:
            raise ValueError("notional_usd must be > 0")

        side = "buy" if dirn == "long" else "sell"
        fill_px = self._fill_price(mid=mid, side=side)
        qty = n_usd / fill_px
        fee = abs(n_usd) * float(self.cfg.fee_rate)

        now = _utc_now().isoformat()

        # idempotency: orders table has unique constraint on idempotency_key.
        idem = idempotency_key
        if idem is None:
            idem = str(uuid.uuid4())

        existing = self.db.conn.execute(
            "SELECT id, position_id, fill_price, fill_size, status FROM orders WHERE idempotency_key = ?",
            (idem,),
        ).fetchone()
        if existing is not None:
            # Already executed.
            oid = str(existing[0])
            pid = str(existing[1])
            return PaperFill(
                order_id=oid,
                position_id=pid,
                symbol=sym,
                side=side,
                fill_price=float(existing[2] or 0.0),
                fill_size=float(existing[3] or 0.0),
                notional_usd=float(n_usd),
                fee_usd=float(fee),
                realized_pnl_usd=None,
            )

        order_id = str(uuid.uuid4())
        position_id = str(uuid.uuid4())

        # For Sprint 2A we open a new position per intent. Closing is done via PnLTracker.
        with self.db.conn:
            self.db.conn.execute(
                """
                INSERT INTO positions (
                  id, platform, asset, direction, entry_price, size_notional, leverage,
                  stop_loss, take_profit, opened_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
                """,
                (
                    position_id,
                    str(self.cfg.platform),
                    sym,
                    dirn,
                    float(fill_px),
                    float(n_usd),
                    float(leverage),
                    float(stop_loss) if stop_loss is not None else None,
                    float(take_profit) if take_profit is not None else None,
                    now,
                ),
            )
            self.db.conn.execute(
                """
                INSERT INTO orders (
                  id, position_id, venue, type, side, symbol, size, price,
                  fill_price, fill_size, status, idempotency_key, created_at, filled_at, updated_at
                ) VALUES (?, ?, ?, 'market', ?, ?, ?, ?, ?, ?, 'filled', ?, ?, ?, ?)
                """,
                (
                    order_id,
                    position_id,
                    str(self.cfg.venue),
                    side,
                    sym,
                    float(qty),
                    None,
                    float(fill_px),
                    float(qty),
                    str(idem),
                    now,
                    now,
                    now,
                ),
            )

        _ = metadata  # reserved
        return PaperFill(
            order_id=order_id,
            position_id=position_id,
            symbol=sym,
            side=side,
            fill_price=float(fill_px),
            fill_size=float(qty),
            notional_usd=float(n_usd),
            fee_usd=float(fee),
            realized_pnl_usd=None,
        )
