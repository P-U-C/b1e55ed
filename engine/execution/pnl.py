"""engine.execution.pnl

P&L tracker for paper/live execution.

Sprint 2A requirements:
- realized P&L on close
- unrealized P&L while holding

The DB schema already has a ``positions`` table, which we treat as the canonical
position ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from engine.core.database import Database


def _utc_now() -> datetime:
    return datetime.now(tz=UTC).replace(microsecond=0)


@dataclass(frozen=True, slots=True)
class PnLSnapshot:
    realized_usd: float
    unrealized_usd: float
    total_usd: float


class PnLTracker:
    def __init__(self, db: Database) -> None:
        self.db = db

    def unrealized_usd(self, *, position_id: str, mark_price: float) -> float:
        row = self.db.conn.execute(
            "SELECT direction, entry_price, size_notional, status FROM positions WHERE id = ?",
            (str(position_id),),
        ).fetchone()
        if row is None:
            return 0.0
        if str(row[3]) != "open":
            return 0.0

        direction = str(row[0])
        entry = float(row[1])
        notional = float(row[2])
        qty = notional / entry if entry > 0 else 0.0
        mp = float(mark_price)

        if direction == "long":
            return (mp - entry) * qty
        return (entry - mp) * qty

    def close_position(self, *, position_id: str, exit_price: float, reason: str = "") -> float:
        """Mark a position closed and store realized_pnl."""

        row = self.db.conn.execute(
            "SELECT direction, entry_price, size_notional, status FROM positions WHERE id = ?",
            (str(position_id),),
        ).fetchone()
        if row is None:
            raise ValueError("position not found")
        if str(row[3]) != "open":
            raise ValueError("position not open")

        direction = str(row[0])
        entry = float(row[1])
        notional = float(row[2])
        qty = notional / entry if entry > 0 else 0.0
        xp = float(exit_price)

        realized = (xp - entry) * qty if direction == "long" else (entry - xp) * qty

        now = _utc_now().isoformat()
        with self.db.conn:
            self.db.conn.execute(
                "UPDATE positions SET status = 'closed', closed_at = ?, realized_pnl = ? WHERE id = ?",
                (now, float(realized), str(position_id)),
            )
            # Optional audit trail
            if reason:
                self.db.conn.execute(
                    "INSERT INTO audit_log (action, actor, component, details) VALUES (?, ?, ?, ?)",
                    ("position_closed", "system", "execution.pnl", f"{position_id}:{reason}"),
                )

        return float(realized)

    def snapshot(self, *, current_prices: dict[str, float]) -> PnLSnapshot:
        unreal = 0.0
        for row in self.db.conn.execute(
            "SELECT id, asset FROM positions WHERE status = 'open'"
        ).fetchall():
            pid = str(row[0])
            sym = str(row[1]).upper()
            px = current_prices.get(sym)
            if px is None:
                continue
            unreal += self.unrealized_usd(position_id=pid, mark_price=float(px))

        realized = 0.0
        for row in self.db.conn.execute(
            "SELECT realized_pnl FROM positions WHERE status = 'closed' AND realized_pnl IS NOT NULL"
        ).fetchall():
            realized += float(row[0])

        return PnLSnapshot(realized_usd=float(realized), unrealized_usd=float(unreal), total_usd=float(realized + unreal))
