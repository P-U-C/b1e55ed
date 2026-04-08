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
from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

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
    max_positions_per_symbol: int = 1
    """Maximum concurrent open positions per symbol. Default 1 (legacy). OMS overrides to
    execution.paper_max_positions_per_symbol from config when constructing PaperBroker."""


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
        row = self.db.fetchone(
            "SELECT * FROM positions WHERE asset = ? AND status = 'open' ORDER BY opened_at DESC LIMIT 1",
            (symbol,),
        )
        return None if row is None else dict(row)

    def _count_open_positions(self, symbol: str) -> int:
        row = self.db.fetchone(
            "SELECT COUNT(*) FROM positions WHERE asset = ? AND status = 'open'",
            (symbol,),
        )
        return int(row[0]) if row else 0

    def _has_open_position_for_direction(self, symbol: str, direction: str) -> bool:
        """Return True if there is already an open position for *symbol* in the same *direction*.

        This prevents the brain from double-firing identical trades on consecutive
        cycles (e.g. two DOGE shorts opened seconds apart with identical parameters).
        """
        row = self.db.fetchone(
            "SELECT 1 FROM positions WHERE asset = ? AND direction = ? AND status = 'open' LIMIT 1",
            (symbol, direction),
        )
        return row is not None

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
        conviction_id: int | None = None,
        regime_at_entry: str | None = None,
        pcs_at_entry: float | None = None,
        cts_at_entry: float | None = None,
        horizon_hours: float | None = None,
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

        existing = self.db.fetchone(
            "SELECT id, position_id, fill_price, fill_size, status FROM orders WHERE idempotency_key = ?",
            (idem,),
        )
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

        # Direction-level deduplication: reject if the same asset+direction is
        # already open.  This prevents the brain from double-firing identical
        # trades on consecutive cycles (e.g. two DOGE shorts seconds apart).
        # A conviction-flip (long -> short or vice-versa) is still allowed.
        if self._has_open_position_for_direction(sym, dirn):
            raise ValueError(
                f"duplicate_open_position: {sym} already has an open {dirn} position"
            )

        # Deduplication: reject if open positions for this symbol exceed the limit.
        # In paper mode paper_max_positions_per_symbol (default 2) allows a second
        # position to open while one is still live — useful for conviction-flip entries.
        # Legacy behaviour (single position per symbol) is max_positions_per_symbol=1.
        open_count = self._count_open_positions(sym)
        max_pos = int(self.cfg.max_positions_per_symbol)
        if open_count >= max_pos:
            raise ValueError(f"duplicate_open_position: {sym} already has {open_count} open position(s) (limit={max_pos})")

        order_id = str(uuid.uuid4())
        position_id = str(uuid.uuid4())

        # For Sprint 2A we open a new position per intent. Closing is done via PnLTracker.
        with self.db._lock, self.db.conn:
            self.db.execute(
                """
                INSERT INTO positions (
                  id, platform, asset, direction, entry_price, size_notional, leverage,
                  stop_loss, take_profit, opened_at, status, conviction_id,
                  regime_at_entry, pcs_at_entry, cts_at_entry, horizon_hours
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?)
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
                    int(conviction_id) if conviction_id is not None else None,
                    str(regime_at_entry) if regime_at_entry is not None else None,
                    float(pcs_at_entry) if pcs_at_entry is not None else None,
                    float(cts_at_entry) if cts_at_entry is not None else None,
                    float(horizon_hours) if horizon_hours is not None else None,
                ),
            )
            self.db.execute(
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
