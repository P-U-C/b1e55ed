"""Karma settlement governance (K1)."""

from pathlib import Path

from engine.core.config import Config
from engine.core.database import Database
from engine.execution.karma import KarmaEngine
from engine.execution.karma_governance import KarmaGovernance
from engine.security.identity import generate_node_identity


def _cfg(tmp_path: Path) -> Config:
    c = Config.from_repo_defaults(repo_root=Path(__file__).resolve().parents[2])
    execution = c.execution.model_copy(update={"mode": "live"})
    karma = c.karma.model_copy(update={"enabled": True, "percentage": 0.005, "treasury_address": "0xTREASURY"})
    return c.model_copy(update={"data_dir": tmp_path / "data", "karma": karma, "execution": execution})


def test_first_settlement_always_allowed(tmp_path: Path) -> None:
    db = Database(tmp_path / "db.sqlite")
    gov = KarmaGovernance(db)

    assert not gov.has_prior_settlement()
    result = gov.check_settlement_allowed(percentage=0.005, treasury_address="0xABC")
    assert result.allowed


def test_wallet_change_blocked_after_settlement(tmp_path: Path) -> None:
    db = Database(tmp_path / "db.sqlite")
    cfg = _cfg(tmp_path)
    ident = generate_node_identity()
    karma = KarmaEngine(config=cfg, db=db, identity=ident)
    gov = KarmaGovernance(db)

    # Create intent and settle
    intent = karma.record_intent(trade_id="t1", realized_pnl_usd=1000.0)
    assert intent is not None
    receipt = karma.settle(intent_ids=[intent.id])
    assert receipt is not None

    # Same wallet = allowed
    result = gov.check_settlement_allowed(percentage=0.005, treasury_address="0xTREASURY")
    assert result.allowed

    # Different wallet without migration = blocked
    result2 = gov.check_settlement_allowed(percentage=0.005, treasury_address="0xNEW_WALLET")
    assert not result2.allowed
    assert "migration" in result2.reason.lower()


def test_wallet_change_allowed_with_migration(tmp_path: Path) -> None:
    db = Database(tmp_path / "db.sqlite")
    cfg = _cfg(tmp_path)
    ident = generate_node_identity()
    karma = KarmaEngine(config=cfg, db=db, identity=ident)
    gov = KarmaGovernance(db)

    # Settle first
    intent = karma.record_intent(trade_id="t1", realized_pnl_usd=500.0)
    assert intent is not None
    karma.settle(intent_ids=[intent.id])

    # Record migration
    gov.record_wallet_migration(
        old_wallet="0xTREASURY",
        new_wallet="0xNEW",
        reason="Treasury rotation",
        authorized_by="operator",
    )

    # Now new wallet is allowed
    result = gov.check_settlement_allowed(percentage=0.005, treasury_address="0xNEW")
    assert result.allowed


def test_audit_log(tmp_path: Path) -> None:
    db = Database(tmp_path / "db.sqlite")
    cfg = _cfg(tmp_path)
    ident = generate_node_identity()
    karma = KarmaEngine(config=cfg, db=db, identity=ident)
    gov = KarmaGovernance(db)

    intent = karma.record_intent(trade_id="t1", realized_pnl_usd=200.0)
    assert intent is not None
    karma.settle(intent_ids=[intent.id])

    log = gov.get_settlement_audit_log()
    assert len(log) >= 1
    assert any("settlement" in entry["type"] for entry in log)
