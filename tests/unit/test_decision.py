from __future__ import annotations

from engine.brain.decision import DecisionEngine
from engine.brain.kill_switch import KillSwitchLevel
from engine.core.database import Database


def test_decision_matrix_and_kill_switch_gating(test_config, temp_dir):
    db = Database(temp_dir / "brain.db")
    dec = DecisionEngine(test_config, db)

    # Allowed trade in bull regime
    intent = dec.decide_and_emit(
        symbol="BTC",
        pcs=80.0,
        regime="BULL",
        kill_level=KillSwitchLevel.SAFE,
        trace_id="t",
    )
    assert intent is not None
    assert intent.symbol == "BTC"

    # Gated by kill switch
    intent2 = dec.decide_and_emit(
        symbol="BTC",
        pcs=95.0,
        regime="BULL",
        kill_level=KillSwitchLevel.DEFENSIVE,
        trace_id="t",
    )
    assert intent2 is None
