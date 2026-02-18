"""End-to-end execution pipeline: intent → preflight → paper fill → karma intent."""

from __future__ import annotations

from pathlib import Path

from engine.brain.kill_switch import KillSwitch
from engine.core.config import Config
from engine.core.database import Database
from engine.core.types import TradeIntent
from engine.execution.karma import KarmaEngine
from engine.execution.oms import OMS, default_sizer_from_config
from engine.execution.paper import PaperBroker
from engine.execution.position_sizer import CorrelationAwareSizer
from engine.core.policy import TradingPolicyEngine
from engine.execution.preflight import Preflight
from engine.security.identity import generate_node_identity


def test_execution_pipeline_intent_to_karma(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    base = Config.from_repo_defaults(repo_root=repo_root)
    cfg = base.model_copy(
        update={
            "data_dir": tmp_path / "data",
            "execution": base.execution.model_copy(update={"mode": "paper"}),
            "karma": base.karma.model_copy(update={"treasury_address": "0xTEST"}),
        }
    )

    db = Database(tmp_path / "db.sqlite")
    ident = generate_node_identity()
    ks = KillSwitch(config=cfg, db=db)
    from engine.core.policy import TradingPolicy
    policy_engine = TradingPolicyEngine(policy=TradingPolicy())

    paper = PaperBroker(db=db)
    preflight = Preflight(policy=policy_engine, kill_switch=ks)
    sizer = default_sizer_from_config(cfg)
    karma = KarmaEngine(config=cfg, db=db, identity=ident)
    oms = OMS(config=cfg, db=db, preflight=preflight, sizer=sizer, paper_broker=paper)

    intent = TradeIntent(
        symbol="BTC",
        direction="long",
        size_pct=0.05,
        leverage=1.0,
        conviction_score=8.0,
        regime="risk_on",
        rationale="test",
    )

    res = oms.submit(
        intent=intent,
        mid_price=100.0,
        equity_usd=10000.0,
    )

    assert res.status == "filled"
    assert res.position_id is not None

    # Simulate a profitable close and record karma
    realized_pnl = 50.0
    karma_intent = karma.record_intent(
        trade_id=res.order_id or "test",
        realized_pnl_usd=realized_pnl,
    )

    assert karma_intent is not None
    assert karma_intent.karma_amount_usd > 0

    pending = karma.get_pending_intents()
    assert len(pending) >= 1

    # Losing trade → no karma
    no_karma = karma.record_intent(trade_id="loser", realized_pnl_usd=-20.0)
    assert no_karma is None
