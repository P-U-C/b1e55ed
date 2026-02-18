from __future__ import annotations

from pathlib import Path

from engine.core.config import Config
from engine.core.database import Database
from engine.execution.karma import KarmaEngine
from engine.execution.oms import OMS, TradeIntent
from engine.execution.paper import PaperAdapter
from engine.execution.preflight import Preflight
from engine.security.identity import generate_node_identity


def test_execution_pipeline_intent_to_karma(tmp_path: Path) -> None:
    base = Config.from_repo_defaults(repo_root=Path(__file__).resolve().parents[2])
    cfg = base.model_copy(
        update={
            "data_dir": tmp_path / "data",
            "execution": base.execution.model_copy(update={"mode": "paper"}),
            "karma": base.karma.model_copy(
                update={
                    "enabled": True,
                    "percentage": 0.005,
                    "treasury_address": "0xPUC_TREASURY_PLACEHOLDER",
                    "settlement_mode": "manual",
                    "threshold_usd": 50.0,
                }
            ),
        }
    )

    db = Database(tmp_path / "db.sqlite")
    ident = generate_node_identity()

    paper = PaperAdapter(db=db)
    preflight = Preflight()
    karma = KarmaEngine(config=cfg, db=db, identity=ident)
    oms = OMS(config=cfg, db=db, paper=paper, preflight=preflight, karma=karma)

    intent = TradeIntent(symbol="BTC", direction="long", size_notional=1000.0, leverage=1.0)
    res = oms.submit(intent=intent, entry_price=100.0)

    pnl = oms.close(trade_id=res.trade_id, position_id=res.position_id, exit_price=110.0)
    assert pnl > 0

    pending = karma.get_pending_intents()
    assert len(pending) == 1
    assert pending[0].trade_id == res.trade_id

    # Settle and confirm receipt
    receipt = karma.settle(intent_ids=[pending[0].id])
    assert receipt is not None
    assert receipt.total_usd == pending[0].karma_amount_usd
