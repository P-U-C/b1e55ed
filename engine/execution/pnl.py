"""engine.execution.pnl

P&L tracker for paper/live execution.

Sprint 2A requirements:
- realized P&L on close
- unrealized P&L while holding

The DB schema already has a ``positions`` table, which we treat as the canonical
position ledger.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017


from engine.core.config import Config
from engine.core.database import Database

_log = logging.getLogger("b1e55ed.execution.pnl")


def _utc_now() -> datetime:
    return datetime.now(tz=UTC).replace(microsecond=0)


@dataclass(frozen=True, slots=True)
class PnLSnapshot:
    realized_usd: float
    unrealized_usd: float
    total_usd: float


class PnLTracker:
    def __init__(self, db: Database, config: Config | None = None) -> None:
        self.db = db
        self._config = config

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

            # KS-1: Consecutive loss tracking
            try:
                if realized < 0:
                    row_cl = self.db.conn.execute("SELECT value FROM system_state WHERE key = 'consecutive_loss_count'").fetchone()
                    count = int(row_cl[0]) if row_cl else 0
                    count += 1
                    self.db.conn.execute(
                        "INSERT OR REPLACE INTO system_state (key, value, updated_at) VALUES ('consecutive_loss_count', ?, datetime('now'))",
                        (str(count),),
                    )
                    if count >= 3 and self._config is not None:
                        from engine.brain.kill_switch import KillSwitch, KillSwitchLevel

                        ks = KillSwitch(self._config, self.db)
                        ks.evaluate(manual_level=KillSwitchLevel.DEFENSIVE, reason="consecutive_losses_3")
                        _log.warning("KS-1: %d consecutive losses, escalating to DEFENSIVE", count)
                else:
                    self.db.conn.execute("INSERT OR REPLACE INTO system_state (key, value, updated_at) VALUES ('consecutive_loss_count', '0', datetime('now'))")
            except Exception:
                _log.warning("KS-1 consecutive loss tracking failed", exc_info=True)

        # Best-effort outcome attribution — never block execution on failure.
        if self._config is not None:
            try:
                from engine.integration.outcome_writer import write_outcome_for_closed_position

                write_outcome_for_closed_position(
                    db=self.db,
                    config=self._config,
                    position_id=str(position_id),
                )
            except Exception:
                _log.warning(
                    "outcome attribution failed for position %s",
                    position_id,
                    exc_info=True,
                )

            # Best-effort karma recording — never block execution on failure.
            try:
                from engine.execution.karma import KarmaEngine
                from engine.security.identity import ensure_identity

                karma = KarmaEngine(
                    config=self._config,
                    db=self.db,
                    identity=ensure_identity().identity,
                )

                # Resolve contributor attribution via conviction_id on the position.
                contributor_id: str | None = None
                try:
                    pos_row = self.db.conn.execute(
                        "SELECT conviction_id FROM positions WHERE id = ?",
                        (str(position_id),),
                    ).fetchone()
                    if pos_row and pos_row["conviction_id"] is not None:
                        contrib_row = self.db.conn.execute(
                            "SELECT node_id FROM conviction_scores WHERE id = ?",
                            (pos_row["conviction_id"],),
                        ).fetchone()
                        if contrib_row and contrib_row["node_id"]:
                            c_row = self.db.conn.execute(
                                "SELECT id FROM contributors WHERE node_id = ?",
                                (str(contrib_row["node_id"]),),
                            ).fetchone()
                            contributor_id = str(c_row["id"]) if c_row else None
                except Exception:
                    contributor_id = None  # fail-open

                karma.record_intent(
                    trade_id=str(position_id),
                    realized_pnl_usd=float(realized),
                    contributor_id=contributor_id,
                )
            except Exception:
                _log.warning(
                    "karma recording failed for position %s",
                    position_id,
                    exc_info=True,
                )

            # Best-effort flywheel attribution — update producer karma scores.
            try:
                from engine.execution.karma import KarmaEngine
                from engine.security.identity import ensure_identity

                karma_attr = KarmaEngine(
                    config=self._config,
                    db=self.db,
                    identity=ensure_identity().identity,
                )
                karma_attr.attribute_outcome(
                    trade_id=str(position_id),
                    realized_pnl_usd=float(realized),
                )
            except Exception:
                _log.warning(
                    "flywheel attribution failed for position %s",
                    position_id,
                    exc_info=True,
                )

            # S7: Record outcome for stratification tracking
            try:
                from engine.brain.learning import StratificationTracker

                strat = StratificationTracker(self.db)
                pos_row2 = self.db.conn.execute(
                    "SELECT conviction_id FROM positions WHERE id = ?",
                    (str(position_id),),
                ).fetchone()
                if pos_row2 and pos_row2["conviction_id"] is not None:
                    cs_row = self.db.conn.execute(
                        "SELECT cycle_id, symbol FROM conviction_scores WHERE id = ?",
                        (pos_row2["conviction_id"],),
                    ).fetchone()
                    if cs_row and cs_row["cycle_id"] and cs_row["symbol"]:
                        sig_id = f"{cs_row['cycle_id']}:{cs_row['symbol']}"
                        strat.record_outcome(sig_id, float(realized), _utc_now())
            except Exception:
                _log.warning(
                    "stratification outcome recording failed for position %s",
                    position_id,
                    exc_info=True,
                )

        return float(realized)

    def check_auto_close(self, *, position_id: str, mark_price: float) -> bool:
        """KS-2: Auto-close if unrealized loss > max_single_loss_pct of portfolio value."""
        try:
            if self._config is None:
                return False
            portfolio_value = float(self._config.risk.portfolio_value_usd)
            threshold = portfolio_value * float(self._config.risk.max_single_loss_pct)
            unrealized = self.unrealized_usd(position_id=position_id, mark_price=mark_price)
            if unrealized < -threshold:
                self.close_position(position_id=position_id, exit_price=mark_price, reason="ks2_auto_close")
                from engine.core.events import EventType

                self.db.append_event(
                    event_type=EventType.AUDIT_V1,
                    payload={"reason": "ks2_single_loss_auto_close", "position_id": position_id, "unrealized": unrealized, "threshold": -threshold},
                    source="execution.pnl",
                )
                _log.warning("KS-2: Auto-closed position %s, unrealized %.2f exceeded threshold %.2f", position_id, unrealized, -threshold)
                return True
        except Exception:
            _log.warning("KS-2 auto-close check failed for %s", position_id, exc_info=True)
        return False

    def snapshot(self, *, current_prices: dict[str, float]) -> PnLSnapshot:
        unreal = 0.0
        for row in self.db.conn.execute("SELECT id, asset FROM positions WHERE status = 'open'").fetchall():
            pid = str(row[0])
            sym = str(row[1]).upper()
            px = current_prices.get(sym)
            if px is None:
                continue
            unreal += self.unrealized_usd(position_id=pid, mark_price=float(px))

        realized = 0.0
        for row in self.db.conn.execute("SELECT realized_pnl FROM positions WHERE status = 'closed' AND realized_pnl IS NOT NULL").fetchall():
            realized += float(row[0])

        return PnLSnapshot(realized_usd=float(realized), unrealized_usd=float(unreal), total_usd=float(realized + unreal))
