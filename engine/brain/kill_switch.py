"""engine.brain.kill_switch

One kill switch. Five levels.

Auto-escalate, never auto-de-escalate.

"L5 is not a bug. It is a feature. The most important one." (Easter egg)
"""

from __future__ import annotations

import contextlib
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


class PauseGate:
    """Single-cycle pause gate with immutable event-log semantics.

    Pause is active when the latest ``system.pause.v1`` event is newer than
    the latest ``system.pause.consumed.v1`` event.

    Consuming a pause writes ``system.pause.consumed.v1`` and never mutates
    existing events.
    """

    def __init__(self, db: Database):
        self.db = db

    def is_paused(self) -> tuple[bool, str | None]:
        """Return ``(paused, reason)`` for the current pause gate state."""
        import json as _json

        try:
            pause_row = self.db.fetchone(
                "SELECT rowid, payload FROM events WHERE type = ? ORDER BY rowid DESC LIMIT 1",
                (EventType.PAUSE_V1.value,),
            )
            if not pause_row:
                return False, None

            pause_rowid = int(pause_row[0])
            pause_payload = pause_row[1]

            consumed_row = self.db.fetchone(
                "SELECT rowid FROM events WHERE type = ? ORDER BY rowid DESC LIMIT 1",
                (EventType.PAUSE_CONSUMED_V1.value,),
            )
            if consumed_row is not None and int(consumed_row[0]) >= pause_rowid:
                return False, None

            data = _json.loads(pause_payload) if isinstance(pause_payload, str) else pause_payload
            if not isinstance(data, dict):
                return True, "operator pause"

            reason = data.get("reason")
            if reason is None or str(reason).strip() == "":
                return True, "operator pause"
            return True, str(reason)
        except Exception:
            return False, None

    def consume(self) -> None:
        """Write a consumed marker for the active pause (best effort)."""
        with contextlib.suppress(Exception):
            self.db.append_event(
                event_type=EventType.PAUSE_CONSUMED_V1,
                payload={"consumed_by": "orchestrator", "auto": True},
                source="brain.orchestrator",
            )


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
            canonical_type = getattr(EventType.KILL_SWITCH_V1, "value", str(EventType.KILL_SWITCH_V1))
            legacy_type = "KILL_SWITCH_V1"
            row = self.db.fetchone(
                "SELECT payload FROM events WHERE type IN (?, ?) ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (canonical_type, legacy_type),
            )
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
            crisis_reason = f"crisis_conditions={crisis_conditions}"
            if why:
                if crisis_reason not in why:
                    why = f"{why};{crisis_reason}"
            else:
                why = crisis_reason

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
