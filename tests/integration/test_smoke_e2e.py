"""Integration smoke tests: full pipeline wiring.

These tests are intentionally end-to-end-ish but still deterministic:
- we write synthetic signal events into the DB (standing in for producers)
- run the brain pipeline pieces (synthesis -> regime -> conviction -> decision)
- route resulting TradeIntents through OMS -> paper broker
- close positions, compute P&L, and record karma intents
- finally, verify the DB event hash chain integrity

The goal is to validate that the major subsystems connect with the real APIs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from engine.brain.conviction import ConvictionEngine
from engine.brain.decision import DecisionEngine
from engine.brain.kill_switch import KillSwitch, KillSwitchLevel
from engine.brain.regime import RegimeDetector
from engine.brain.synthesis import VectorSynthesis
from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType
from engine.core.policy import TradingPolicy, TradingPolicyEngine
from engine.core.types import TradeIntent
from engine.execution.karma import KarmaEngine
from engine.execution.oms import OMS, default_sizer_from_config
from engine.execution.paper import PaperBroker
from engine.execution.pnl import PnLTracker
from engine.execution.preflight import Preflight
from engine.security.identity import generate_node_identity


def _base_cfg(repo_root: Path, tmp_path: Path) -> Config:
    base = Config.from_repo_defaults(repo_root=repo_root)
    return base.model_copy(
        update={
            "data_dir": tmp_path / "data",
            "execution": base.execution.model_copy(update={"mode": "paper"}),
            # For karma tests we will override treasury_address as needed.
        }
    )


def _append_mock_signals(db: Database, *, symbol: str, ts: datetime) -> None:
    """Append a representative cross-domain signal set for a given symbol."""

    sym = str(symbol).upper()

    db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": sym, "rsi_14": 30.0, "trend_strength": 0.9, "volume_ratio": 1.5},
        source="producer.ta",
        ts=ts,
    )
    db.append_event(
        event_type=EventType.SIGNAL_SENTIMENT_V1,
        payload={"symbol": sym, "fear_greed": 35.0, "fear_greed_change_7d": -10.0},
        source="producer.sentiment",
        ts=ts,
    )
    db.append_event(
        event_type=EventType.SIGNAL_ONCHAIN_V1,
        payload={"symbol": sym, "whale_netflow": 75.0, "exchange_flow": -25.0, "price_momentum_24h": 4.0},
        source="producer.onchain",
        ts=ts,
    )

    # Add tradfi in a non-extreme range so regime detector can classify BULL.
    db.append_event(
        event_type=EventType.SIGNAL_TRADFI_V1,
        payload={"symbol": sym, "funding_annualized": 12.0, "basis_annualized": 4.5, "oi_change_pct": 5.0},
        source="producer.tradfi",
        ts=ts,
    )


def test_producer_to_brain_cycle(tmp_path: Path) -> None:
    """Signals -> synthesis -> regime -> conviction -> decision produces coherent output."""

    repo_root = Path(__file__).resolve().parents[2]
    cfg = _base_cfg(repo_root, tmp_path)

    db = Database(tmp_path / "db.sqlite")
    ident = generate_node_identity()

    now = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    _append_mock_signals(db, symbol="BTC", ts=now)

    synthesis = VectorSynthesis(cfg, db)
    synth_res = synthesis.synthesize(cycle_id="cycle-1", symbol="BTC", as_of=now)

    regime = RegimeDetector(db)
    reg_res = regime.detect(as_of=now, btc_snapshot=synth_res.snapshot)

    conviction = ConvictionEngine(cfg, db, node_id=ident.node_id)
    conv_res = conviction.compute(synthesis=synth_res, regime=reg_res.state.regime, as_of=now)

    decision = DecisionEngine(cfg, db)
    intent = decision.decide_and_emit(
        symbol="BTC",
        pcs=conv_res.final_conviction,
        regime=reg_res.state.regime,
        kill_level=KillSwitchLevel.SAFE,
        trace_id="cycle-1",
    )

    # Coherent conviction output.
    assert conv_res.score.symbol == "BTC"
    assert 0.0 <= conv_res.final_conviction <= 100.0
    assert conv_res.score.direction in {"long", "short", "neutral"}

    # Decision is allowed to be neutral (None), but if it fires it must match the contract.
    if intent is not None:
        assert intent.symbol == "BTC"
        assert intent.direction in {"long", "short"}
        assert 0.0 < intent.size_pct <= cfg.risk.max_position_pct

    # And the brain should have emitted an event when it fires.
    events = db.get_events(event_type=EventType.TRADE_INTENT_V1, limit=10)
    if intent is not None:
        assert events, "Decision emitted intent but no TRADE_INTENT_V1 event was stored"
        assert events[0].payload["symbol"] == "BTC"

    db.close()


def test_brain_to_execution_pipeline(tmp_path: Path) -> None:
    """TradeIntent -> OMS(paper) -> fill -> position row + execution events."""

    repo_root = Path(__file__).resolve().parents[2]
    cfg = _base_cfg(repo_root, tmp_path)

    db = Database(tmp_path / "db.sqlite")

    ks = KillSwitch(config=cfg, db=db)
    policy_engine = TradingPolicyEngine(policy=TradingPolicy())
    preflight = Preflight(policy=policy_engine, kill_switch=ks)

    paper = PaperBroker(db=db)
    sizer = default_sizer_from_config(cfg)
    oms = OMS(config=cfg, db=db, preflight=preflight, sizer=sizer, paper_broker=paper)

    intent = TradeIntent(
        symbol="BTC",
        direction="long",
        size_pct=0.05,
        leverage=1.0,
        conviction_score=80.0,  # OMS expects 0..100 here
        regime="BULL",
        rationale="smoke",
        stop_loss_pct=0.05,
        take_profit_pct=0.10,
    )

    res = oms.submit(intent=intent, mid_price=100.0, equity_usd=10_000.0)
    assert res.status == "filled"
    assert res.order_id is not None
    assert res.position_id is not None

    # Position persisted.
    row = db.conn.execute(
        "SELECT status, asset, direction, entry_price FROM positions WHERE id = ?",
        (res.position_id,),
    ).fetchone()
    assert row is not None
    assert str(row[0]) == "open"
    assert str(row[1]).upper() == "BTC"
    assert str(row[2]) == "long"
    assert float(row[3]) > 0.0

    # Execution events emitted.
    filled = db.get_events(event_type=EventType.ORDER_FILLED_V1, limit=10)
    opened = db.get_events(event_type=EventType.POSITION_OPENED_V1, limit=10)
    assert filled, "Expected ORDER_FILLED_V1 event"
    assert opened, "Expected POSITION_OPENED_V1 event"

    db.close()


def test_full_pipeline_profit_to_karma(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Full loop: signals -> brain (intent) -> OMS -> paper fill -> price move -> close -> karma intent."""

    repo_root = Path(__file__).resolve().parents[2]
    base = _base_cfg(repo_root, tmp_path)
    cfg = base.model_copy(update={"karma": base.karma.model_copy(update={"treasury_address": "0xTEST"})})

    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "test")
    ident = generate_node_identity()

    db = Database(tmp_path / "db.sqlite")
    now = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

    # Producer outputs.
    _append_mock_signals(db, symbol="BTC", ts=now)

    # Brain.
    synth_res = VectorSynthesis(cfg, db).synthesize(cycle_id="cycle-2", symbol="BTC", as_of=now)
    regime = RegimeDetector(db).detect(as_of=now, btc_snapshot=synth_res.snapshot)
    conv = ConvictionEngine(cfg, db, node_id=ident.node_id).compute(synthesis=synth_res, regime=regime.state.regime, as_of=now)

    intent = DecisionEngine(cfg, db).decide_and_emit(
        symbol="BTC",
        pcs=conv.final_conviction,
        regime=regime.state.regime,
        kill_level=KillSwitchLevel.SAFE,
        trace_id="cycle-2",
    )

    # If decision doesn't fire (depending on weights), force a plausible intent to validate execution wiring.
    if intent is None:
        intent = TradeIntent(
            symbol="BTC",
            direction="long",
            size_pct=0.05,
            leverage=1.0,
            conviction_score=80.0,
            regime=regime.state.regime,
            rationale="forced intent for smoke",
            stop_loss_pct=0.05,
            take_profit_pct=0.10,
        )

    # Execution.
    ks = KillSwitch(config=cfg, db=db)
    policy_engine = TradingPolicyEngine(policy=TradingPolicy())
    preflight = Preflight(policy=policy_engine, kill_switch=ks)
    oms = OMS(
        config=cfg,
        db=db,
        preflight=preflight,
        sizer=default_sizer_from_config(cfg),
        paper_broker=PaperBroker(db=db),
    )

    res = oms.submit(intent=intent, mid_price=100.0, equity_usd=10_000.0)
    assert res.status == "filled"
    assert res.position_id is not None

    # Simulate profitable move and close.
    pnl = PnLTracker(db)
    entry = db.conn.execute("SELECT entry_price FROM positions WHERE id = ?", (res.position_id,)).fetchone()[0]
    exit_px = float(entry) * 1.10
    realized = pnl.close_position(position_id=res.position_id, exit_price=exit_px, reason="smoke")
    assert realized > 0.0

    # Karma.
    karma = KarmaEngine(config=cfg, db=db, identity=ident)
    k_intent = karma.record_intent(trade_id=res.order_id or "order", realized_pnl_usd=realized)
    assert k_intent is not None

    rows = db.conn.execute("SELECT COUNT(*) FROM karma_intents").fetchone()
    assert int(rows[0]) >= 1

    karma_events = db.get_events(event_type=EventType.KARMA_INTENT_V1, limit=50)
    assert karma_events, "Expected KARMA_INTENT_V1 event"

    db.close()


def test_kill_switch_blocks_execution(tmp_path: Path) -> None:
    """Kill switch level 3+ should hard-block OMS via Preflight/policy."""

    repo_root = Path(__file__).resolve().parents[2]
    cfg = _base_cfg(repo_root, tmp_path)

    db = Database(tmp_path / "db.sqlite")
    ks = KillSwitch(config=cfg, db=db)
    _ = ks.evaluate(manual_level=KillSwitchLevel.LOCKDOWN, reason="test")
    assert ks.level >= KillSwitchLevel.LOCKDOWN

    policy_engine = TradingPolicyEngine(policy=TradingPolicy())
    preflight = Preflight(policy=policy_engine, kill_switch=ks)

    oms = OMS(
        config=cfg,
        db=db,
        preflight=preflight,
        sizer=default_sizer_from_config(cfg),
        paper_broker=PaperBroker(db=db),
    )

    intent = TradeIntent(
        symbol="BTC",
        direction="long",
        size_pct=0.05,
        leverage=1.0,
        conviction_score=80.0,
        regime="BULL",
        rationale="smoke",
    )

    res = oms.submit(intent=intent, mid_price=100.0, equity_usd=10_000.0)
    assert res.status == "rejected"
    assert res.reasons is not None
    assert "kill_switch" in set(res.reasons)

    db.close()


def test_event_hash_chain_integrity(tmp_path: Path) -> None:
    """After a cycle, verify DB event prev_hash links match the prior event's hash."""

    repo_root = Path(__file__).resolve().parents[2]
    cfg = _base_cfg(repo_root, tmp_path)

    db = Database(tmp_path / "db.sqlite")

    # Create a small end-to-end event stream.
    now = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    _append_mock_signals(db, symbol="BTC", ts=now)

    ident = generate_node_identity()

    synth_res = VectorSynthesis(cfg, db).synthesize(cycle_id="cycle-3", symbol="BTC", as_of=now)
    reg = RegimeDetector(db).detect(as_of=now, btc_snapshot=synth_res.snapshot)
    conv = ConvictionEngine(cfg, db, node_id=ident.node_id).compute(synthesis=synth_res, regime=reg.state.regime, as_of=now)
    DecisionEngine(cfg, db).decide_and_emit(
        symbol="BTC",
        pcs=conv.final_conviction,
        regime=reg.state.regime,
        kill_level=KillSwitchLevel.SAFE,
        trace_id="cycle-3",
    )

    assert db.verify_hash_chain(fast=False) is True

    # Manual chain check over all events, ordered by insertion.
    rows = db.conn.execute("SELECT prev_hash, hash FROM events ORDER BY created_at ASC, rowid ASC").fetchall()
    assert rows, "Expected at least one event in DB"

    prev = None
    for r in rows:
        prev_hash = r[0]
        h = str(r[1])
        if prev is None:
            # Genesis event uses well-known prev_hash, not None.
            assert prev_hash == "0" * 64 or prev_hash is None
        else:
            assert str(prev_hash) == prev
        prev = h

    db.close()
