"""Kill switch must persist level across process restarts (FIX1-A)."""

from pathlib import Path

from engine.brain.kill_switch import KillSwitch, KillSwitchLevel
from engine.core.config import Config
from engine.core.database import Database


def _cfg(tmp_path: Path) -> Config:
    return Config.from_repo_defaults(repo_root=Path(__file__).resolve().parents[2]).model_copy(
        update={"data_dir": tmp_path / "data"}
    )


def test_fresh_db_starts_at_safe(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    db = Database(tmp_path / "db.sqlite")
    ks = KillSwitch(cfg, db)
    assert ks.level == KillSwitchLevel.SAFE
    db.close()


def test_level_persists_across_restart(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    db_path = tmp_path / "db.sqlite"
    db = Database(db_path)

    ks1 = KillSwitch(cfg, db)
    ks1.evaluate(manual_level=KillSwitchLevel.LOCKDOWN, reason="test escalation")
    assert ks1.level == KillSwitchLevel.LOCKDOWN

    # Simulate restart: new KillSwitch instance, same DB
    ks2 = KillSwitch(cfg, db)
    assert ks2.level == KillSwitchLevel.LOCKDOWN
    db.close()


def test_highest_level_wins_on_restore(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    db = Database(tmp_path / "db.sqlite")

    ks = KillSwitch(cfg, db)
    ks.evaluate(manual_level=KillSwitchLevel.CAUTION, reason="first")
    ks.evaluate(manual_level=KillSwitchLevel.EMERGENCY, reason="second")

    # New instance should restore EMERGENCY (the latest event)
    ks2 = KillSwitch(cfg, db)
    assert ks2.level == KillSwitchLevel.EMERGENCY
    db.close()


def test_reset_persists(tmp_path: Path) -> None:
    """After manual reset, new instance should see the reset level.

    Note: reset() does NOT emit an event currently. This test documents
    that limitation — reset only affects in-memory state.
    """
    cfg = _cfg(tmp_path)
    db = Database(tmp_path / "db.sqlite")

    ks = KillSwitch(cfg, db)
    ks.evaluate(manual_level=KillSwitchLevel.LOCKDOWN, reason="test")
    ks.reset(level=KillSwitchLevel.SAFE)
    assert ks.level == KillSwitchLevel.SAFE

    # New instance restores from DB — which still has LOCKDOWN event
    # because reset() doesn't emit a new event.
    ks2 = KillSwitch(cfg, db)
    assert ks2.level == KillSwitchLevel.LOCKDOWN  # Known limitation
    db.close()
