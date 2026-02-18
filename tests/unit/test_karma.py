from __future__ import annotations

import base64
from pathlib import Path

from engine.core.config import Config
from engine.core.database import Database
from engine.execution.karma import KarmaEngine
from engine.security.identity import generate_node_identity


def _cfg(tmp_path: Path) -> Config:
    c = Config.from_repo_defaults(repo_root=Path(__file__).resolve().parents[2])
    karma = c.karma.model_copy(
        update={
            "enabled": True,
            "percentage": 0.005,
            "settlement_mode": "manual",
            "threshold_usd": 50.0,
            "treasury_address": "0xPUC_TREASURY_PLACEHOLDER",
        }
    )
    return c.model_copy(update={"data_dir": tmp_path / "data", "karma": karma})


def test_intent_on_profit(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    db = Database(tmp_path / "db.sqlite")
    ident = generate_node_identity()

    k = KarmaEngine(config=cfg, db=db, identity=ident)
    intent = k.record_intent(trade_id="t1", realized_pnl_usd=100.0)

    assert intent is not None
    assert intent.trade_id == "t1"
    assert intent.realized_pnl_usd == 100.0
    assert abs(intent.karma_amount_usd - 0.5) < 1e-9

    # signature is valid base64
    base64.b64decode(intent.signature_b64)


def test_no_intent_on_loss(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    db = Database(tmp_path / "db.sqlite")
    ident = generate_node_identity()

    k = KarmaEngine(config=cfg, db=db, identity=ident)

    assert k.record_intent(trade_id="t2", realized_pnl_usd=-10.0) is None
    assert k.record_intent(trade_id="t2", realized_pnl_usd=0.0) is None


def test_percentage_calc(tmp_path: Path) -> None:
    base = _cfg(tmp_path)
    cfg = base.model_copy(update={"karma": base.karma.model_copy(update={"percentage": 0.01, "treasury_address": "0xT"})})
    db = Database(tmp_path / "db.sqlite")
    ident = generate_node_identity()

    k = KarmaEngine(config=cfg, db=db, identity=ident)
    intent = k.record_intent(trade_id="t3", realized_pnl_usd=250.0)
    assert intent is not None
    assert abs(intent.karma_amount_usd - 2.5) < 1e-9


def test_signing_round_trip(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    db = Database(tmp_path / "db.sqlite")
    ident = generate_node_identity()

    k = KarmaEngine(config=cfg, db=db, identity=ident)
    intent = k.record_intent(trade_id="t4", realized_pnl_usd=10.0)
    assert intent is not None

    # Verify signature against canonical json payload
    payload = {
        "id": intent.id,
        "trade_id": intent.trade_id,
        "realized_pnl_usd": intent.realized_pnl_usd,
        "karma_percentage": intent.karma_percentage,
        "karma_amount_usd": intent.karma_amount_usd,
        "node_id": intent.node_id,
        "created_at": intent.created_at,
    }
    # Canonical json lives in engine.core.events
    from engine.core.events import canonical_json

    msg = canonical_json(payload).encode("utf-8")
    sig = base64.b64decode(intent.signature_b64)
    assert ident.verify(sig, msg) is True


def test_non_blocking_on_db_failure(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    db = Database(tmp_path / "db.sqlite")
    ident = generate_node_identity()

    k = KarmaEngine(config=cfg, db=db, identity=ident)

    # Break the table to force an exception
    with db.conn:
        db.conn.execute("DROP TABLE karma_intents")

    # Must not raise
    assert k.record_intent(trade_id="t5", realized_pnl_usd=100.0) is None


def test_settlement_batch_and_receipt(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    db = Database(tmp_path / "db.sqlite")
    ident = generate_node_identity()

    k = KarmaEngine(config=cfg, db=db, identity=ident)
    i1 = k.record_intent(trade_id="a", realized_pnl_usd=100.0)
    i2 = k.record_intent(trade_id="b", realized_pnl_usd=200.0)
    assert i1 is not None and i2 is not None

    pending = k.get_pending_intents()
    assert {p.id for p in pending} == {i1.id, i2.id}

    receipt = k.settle(intent_ids=[i1.id, i2.id], tx_hash=None)
    assert receipt is not None
    assert set(receipt.intent_ids) == {i1.id, i2.id}
    assert abs(receipt.total_usd - (i1.karma_amount_usd + i2.karma_amount_usd)) < 1e-9

    # Pending should now be empty
    assert k.get_pending_intents() == []

    receipts = k.get_receipts()
    assert len(receipts) == 1
    assert receipts[0].id == receipt.id
