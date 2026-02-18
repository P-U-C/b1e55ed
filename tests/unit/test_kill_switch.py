from __future__ import annotations

from engine.brain.kill_switch import KillSwitch, KillSwitchLevel
from engine.core.database import Database


def test_kill_switch_5_levels_escalates_and_never_auto_deescalates(test_config, temp_dir):
    db = Database(temp_dir / "brain.db")
    ks = KillSwitch(test_config, db)

    assert ks.level == KillSwitchLevel.SAFE

    d1 = ks.evaluate(daily_loss_pct=test_config.kill_switch.l1_daily_loss_pct + 0.01)
    assert d1 is not None
    assert ks.level == KillSwitchLevel.CAUTION

    # Escalate
    d2 = ks.evaluate(portfolio_heat_pct=test_config.kill_switch.l2_portfolio_heat_pct + 0.01)
    assert d2 is not None
    assert ks.level == KillSwitchLevel.DEFENSIVE

    # Attempt to de-escalate by providing safe values does nothing
    d3 = ks.evaluate(daily_loss_pct=0.0, portfolio_heat_pct=0.0, crisis_conditions=0, max_drawdown_pct=0.0)
    assert d3 is None
    assert ks.level == KillSwitchLevel.DEFENSIVE

    # Manual L5
    d5 = ks.evaluate(manual_level=KillSwitchLevel.SHUTDOWN, reason="manual_test")
    assert d5 is not None
    assert ks.level == KillSwitchLevel.SHUTDOWN
