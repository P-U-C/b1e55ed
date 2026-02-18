from __future__ import annotations

import pytest

from engine.brain.position_sm import PositionState, PositionStateMachine


def test_position_state_transitions():
    sm = PositionStateMachine()

    t1 = sm.transition(state=PositionState.OPEN, new_state=PositionState.MONITORING, reason="opened")
    assert t1.new == PositionState.MONITORING

    t2 = sm.transition(state=PositionState.MONITORING, new_state=PositionState.DEGRADING, reason="thesis_degraded")
    assert t2.new == PositionState.DEGRADING

    t3 = sm.transition(state=PositionState.DEGRADING, new_state=PositionState.CLOSING, reason="stop_hit")
    assert t3.new == PositionState.CLOSING

    t4 = sm.transition(state=PositionState.CLOSING, new_state=PositionState.CLOSED, reason="filled")
    assert t4.new == PositionState.CLOSED

    with pytest.raises(ValueError):
        sm.transition(state=PositionState.CLOSED, new_state=PositionState.OPEN, reason="invalid")
