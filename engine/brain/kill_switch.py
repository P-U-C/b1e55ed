"""engine.brain.kill_switch

One kill switch. Five levels.

Auto-escalate, never auto-de-escalate.

"L5 is not a bug. It is a feature. The most important one." (Easter egg)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType


class KillSwitchLevel(IntEnum):
    SAFE = 0
    CAUTION = 1
    DEFENSIVE = 2
    LOCKDOWN = 3
    EMERGENCY = 4
    SHUTDOWN = 5


LEVEL_MESSAGES: dict[KillSwitchLevel, str] = {
    KillSwitchLevel.SAFE: "Normal operation.",
    KillSwitchLevel.CAUTION: "Caution. Reduce size. Tighten stops.",
    KillSwitchLevel.DEFENSIVE: "Defensive. No new positions.",
    KillSwitchLevel.LOCKDOWN: "Lockdown. Close non-core. Halt new.",
    KillSwitchLevel.EMERGENCY: "Emergency. Close everything.",
    KillSwitchLevel.SHUTDOWN: "L5 is not a bug. It is a feature. The most important one.",
}


@dataclass(frozen=True, slots=True)
class KillSwitchDecision:
    level: KillSwitchLevel
    previous_level: KillSwitchLevel
    reason: str
    auto: bool


class KillSwitch:
    """A deterministic kill switch state machine."""

    def __init__(self, config: Config, db: Database):
        self.config = config
        self.db = db
        self._level: KillSwitchLevel = KillSwitchLevel.SAFE
        self._restore_from_db()

    def _restore_from_db(self) -> None:
        """Restore kill switch level from the latest persisted event.

        Without this, the kill switch resets to SAFE on every process restart —
        meaning the 5-minute brain cron effectively has no kill switch at all.
        """
        import json as _json

        try:
            row = self.db.conn.execute(
                "SELECT payload FROM events WHERE type = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (str(EventType.KILL_SWITCH_V1),),
            ).fetchone()
            if row:
                data = _json.loads(row[0])
                persisted = int(data.get("level", 0))
                self._level = KillSwitchLevel(persisted)
        except Exception:
            # Fail-open: if we can't read, stay at SAFE (existing behavior).
            pass

    @property
    def level(self) -> KillSwitchLevel:
        return self._level

    def evaluate(
        self,
        *,
        daily_loss_pct: float | None = None,
        portfolio_heat_pct: float | None = None,
        crisis_conditions: int | None = None,
        max_drawdown_pct: float | None = None,
        manual_level: KillSwitchLevel | None = None,
        reason: str | None = None,
    ) -> KillSwitchDecision | None:
        """Return an escalation decision or None."""

        prev = self._level
        target = prev
        auto = True
        why = reason or ""

        if manual_level is not None:
            target = max(target, KillSwitchLevel(int(manual_level)))
            auto = False
            why = why or f"manual:{int(manual_level)}"

        # Auto triggers (ascending severity):
        if daily_loss_pct is not None and daily_loss_pct >= self.config.kill_switch.l1_daily_loss_pct:
            target = max(target, KillSwitchLevel.CAUTION)
            why = why or f"daily_loss_pct={daily_loss_pct:.3f}"

        if portfolio_heat_pct is not None and portfolio_heat_pct >= self.config.kill_switch.l2_portfolio_heat_pct:
            target = max(target, KillSwitchLevel.DEFENSIVE)
            why = why or f"portfolio_heat_pct={portfolio_heat_pct:.3f}"

        if crisis_conditions is not None and crisis_conditions >= self.config.kill_switch.l3_crisis_threshold:
            target = max(target, KillSwitchLevel.LOCKDOWN)
            why = why or f"crisis_conditions={crisis_conditions}"

        if max_drawdown_pct is not None and max_drawdown_pct >= self.config.kill_switch.l4_max_drawdown_pct:
            target = max(target, KillSwitchLevel.EMERGENCY)
            why = why or f"max_drawdown_pct={max_drawdown_pct:.3f}"

        if target <= prev:
            return None

        self._level = target
        dec = KillSwitchDecision(level=target, previous_level=prev, reason=why, auto=auto)

        payload = {
            "level": int(target),
            "previous_level": int(prev),
            "reason": why or LEVEL_MESSAGES[target],
            "auto": bool(auto),
            "actor": "system" if auto else "operator",
        }
        self.db.append_event(event_type=EventType.KILL_SWITCH_V1, payload=payload, source="brain.kill_switch")
        return dec

    def can_open_new_positions(self) -> bool:
        return self._level < KillSwitchLevel.DEFENSIVE

    def can_trade(self) -> bool:
        return self._level < KillSwitchLevel.SHUTDOWN

    def reset(self, *, level: KillSwitchLevel = KillSwitchLevel.SAFE) -> None:
        # Manual reset only (tests may use this). Not auto-called.
        self._level = KillSwitchLevel(int(level))
