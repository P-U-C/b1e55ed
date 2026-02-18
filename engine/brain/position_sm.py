"""engine.brain.position_sm

Position state machine.

v3 requirement (SDD §7):
OPEN → MONITORING → DEGRADING → CLOSING → CLOSED

This is a deterministic lifecycle model. It does *not* execute trades; it
restricts which actions are allowed in each state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class PositionState(StrEnum):
    OPEN = "open"
    MONITORING = "monitoring"
    DEGRADING = "degrading"
    CLOSING = "closing"
    CLOSED = "closed"


ALLOWED_TRANSITIONS: Final[dict[PositionState, set[PositionState]]] = {
    PositionState.OPEN: {PositionState.MONITORING, PositionState.CLOSING},
    PositionState.MONITORING: {PositionState.DEGRADING, PositionState.CLOSING},
    PositionState.DEGRADING: {PositionState.MONITORING, PositionState.CLOSING},
    PositionState.CLOSING: {PositionState.CLOSED},
    PositionState.CLOSED: set(),
}


ALLOWED_ACTIONS: Final[dict[PositionState, set[str]]] = {
    PositionState.OPEN: {"hold", "reduce", "close"},
    PositionState.MONITORING: {"hold", "reduce", "close", "tighten_stop", "take_profit"},
    PositionState.DEGRADING: {"reduce", "close", "tighten_stop"},
    PositionState.CLOSING: {"close"},
    PositionState.CLOSED: set(),
}


@dataclass(frozen=True, slots=True)
class PositionTransition:
    previous: PositionState
    new: PositionState
    reason: str


class PositionStateMachine:
    def transition(self, *, state: PositionState, new_state: PositionState, reason: str) -> PositionTransition:
        allowed = ALLOWED_TRANSITIONS.get(state, set())
        if new_state not in allowed:
            raise ValueError(f"Invalid transition {state} -> {new_state}")
        return PositionTransition(previous=state, new=new_state, reason=reason)

    def allowed_actions(self, *, state: PositionState) -> set[str]:
        return set(ALLOWED_ACTIONS.get(state, set()))
