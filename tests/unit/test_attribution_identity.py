"""tests/unit/test_attribution_identity.py

Regression tests for attribution identity correctness.

P0-1: canonical trade identity is position_id, not order_id.
Wave-1: source_event_ids is the only authoritative attribution source — DB signal
        lookup must NOT inflate attribution with unrelated recent signals.

Covers:
- test_signal_accepted_links_to_position_id
- test_close_position_finds_signal_accepted_events
- test_producer_karma_updates_after_position_close
- test_only_snapshot_signals_get_accepted (Wave-1)
- test_unrelated_recent_signals_not_credited (Wave-1)
"""

from __future__ import annotations

import json
from pathlib import Path

from engine.brain.kill_switch import KillSwitch
from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType, SignalAcceptedPayload
from engine.core.policy import TradingPolicy, TradingPolicyEngine
from engine.core.types import TradeIntent
from engine.execution.karma import KarmaEngine
from engine.execution.oms import OMS, default_sizer_from_config
from engine.execution.paper import PaperBroker
from engine.execution.preflight import Preflight
from engine.security.identity import generate_node_identity

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _karma_config(tmp_path: Path) -> Config:
    """Return a Config with karma enabled, pointing data to tmp_path."""
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
    execution = c.execution.model_copy(update={"mode": "paper"})
    return c.model_copy(update={"data_dir": tmp_path / "data", "karma": karma, "execution": execution})


def _make_oms(tmp_path: Path, cfg: Config, db: Database) -> OMS:
    ks = KillSwitch(cfg, db)
    pol = TradingPolicy(
        max_daily_loss_usd=0.0,
        max_position_size_pct=cfg.risk.max_position_pct,
        kill_switch_enabled=True,
        max_leverage_default=cfg.risk.max_leverage,
    )
    policy_engine = TradingPolicyEngine(policy=pol)
    preflight = Preflight(policy=policy_engine, kill_switch=ks)
    sizer = default_sizer_from_config(cfg)
    return OMS(config=cfg, db=db, preflight=preflight, sizer=sizer)


def _make_intent_with_source_event(db: Database) -> tuple[TradeIntent, str]:
    """Insert a raw signal event and return an intent that references it."""
    ev = db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "BTC", "direction": "long", "confidence": 0.8},
        source="producer.ta",
    )
    ev_id = ev.id  # append_event returns an Event object
    intent = TradeIntent(
        symbol="BTC",
        direction="long",
        size_pct=0.05,
        leverage=1.0,
        conviction_score=80.0,
        regime="BULL",
        rationale="unit test attribution",
        source_event_ids=[ev_id],
    )
    return intent, ev_id


# ---------------------------------------------------------------------------
# Test 1: OMS emits SIGNAL_ACCEPTED_V1 with trade_id == position_id
# ---------------------------------------------------------------------------


def test_signal_accepted_links_to_position_id(tmp_path: Path, test_config: Config) -> None:
    """SIGNAL_ACCEPTED_V1 events must carry trade_id == position_id, NOT order_id.

    This is the canonical identity required by karma.py and pnl.py for
    downstream attribution lookups.
    """
    db = Database(tmp_path / "db.sqlite")
    oms = _make_oms(tmp_path, test_config, db)

    intent, _ = _make_intent_with_source_event(db)
    result = oms.submit(intent, mid_price=50_000.0, equity_usd=10_000.0)

    assert result.status == "filled"
    position_id = result.position_id
    order_id = result.order_id
    assert position_id is not None
    assert order_id is not None
    # The two IDs must be distinct UUIDs (if they were equal the bug would be hidden)
    assert position_id != order_id

    # Find SIGNAL_ACCEPTED_V1 events
    signal_events = [e for e in db.get_events(limit=100) if str(e.type) == str(EventType.SIGNAL_ACCEPTED_V1)]
    assert signal_events, "Expected at least one SIGNAL_ACCEPTED_V1 event"

    for ev in signal_events:
        payload = ev.payload if isinstance(ev.payload, dict) else json.loads(ev.payload)
        # The trade_id in the attribution event must match position_id, not order_id.
        assert payload["trade_id"] == position_id, (
            f"SIGNAL_ACCEPTED_V1 trade_id is '{payload['trade_id']}' "
            f"but expected position_id='{position_id}' (order_id='{order_id}'). "
            "Attribution identity mismatch: karma.py and pnl.py use position_id for lookups."
        )


# ---------------------------------------------------------------------------
# Test 2: close_position can find SIGNAL_ACCEPTED_V1 events via position_id
# ---------------------------------------------------------------------------


def test_close_position_finds_signal_accepted_events(tmp_path: Path) -> None:
    """After close_position, attribute_outcome must find the SIGNAL_ACCEPTED_V1 events.

    Previously OMS stored them under order_id, so the lookup by position_id always
    returned zero events, silently breaking the flywheel.
    """
    db = Database(tmp_path / "db.sqlite")
    broker = PaperBroker(db)
    fill = broker.execute_market(
        symbol="BTC",
        direction="long",
        notional_usd=1000.0,
        leverage=1.0,
        mid_price=50_000.0,
    )

    position_id = fill.position_id

    # Store a SIGNAL_ACCEPTED_V1 event using position_id as trade_id
    # (this is what the fixed OMS code now does)
    payload = SignalAcceptedPayload(
        trade_id=position_id,  # canonical: position_id
        producer_id="producer.technical",
        domain="technical",
        signal_event_id="evt-test-001",
        contribution_weight=1.0,
        direction="long",
        confidence=80.0,
    ).model_dump(mode="json")
    db.append_event(
        event_type=EventType.SIGNAL_ACCEPTED_V1,
        payload=payload,
        source="test",
    )

    cfg = Config.from_repo_defaults(repo_root=Path(__file__).resolve().parents[2])
    cfg = cfg.model_copy(update={"data_dir": tmp_path / "data"})

    identity = generate_node_identity()
    karma = KarmaEngine(config=cfg, db=db, identity=identity)

    # attribute_outcome uses position_id to look up SIGNAL_ACCEPTED events
    result = karma.attribute_outcome(
        trade_id=position_id,
        realized_pnl_usd=200.0,
    )

    assert result, "attribute_outcome returned empty — SIGNAL_ACCEPTED_V1 lookup failed"
    assert result.get("producers_updated", 0) >= 1, (
        f"Expected at least 1 producer updated, got: {result}. Lookup may still be using order_id instead of position_id."
    )


# ---------------------------------------------------------------------------
# Test 3: Full round-trip — producer karma updates after position close
# ---------------------------------------------------------------------------


def test_producer_karma_updates_after_position_close(tmp_path: Path) -> None:
    """End-to-end: insert signal → open position → close position → karma updated.

    This tests that the full attribution flywheel works when position_id is used
    as the canonical identity throughout. If order_id were still used, the karma
    score would not update because attribute_outcome wouldn't find any events.
    """
    db = Database(tmp_path / "db.sqlite")
    broker = PaperBroker(db)
    fill = broker.execute_market(
        symbol="ETH",
        direction="long",
        notional_usd=500.0,
        leverage=1.0,
        mid_price=3_000.0,
    )

    position_id = fill.position_id
    producer_id = "producer.onchain"

    # Simulate what the fixed OMS emits: SIGNAL_ACCEPTED_V1 keyed by position_id
    payload = SignalAcceptedPayload(
        trade_id=position_id,  # canonical: position_id
        producer_id=producer_id,
        domain="onchain",
        signal_event_id="evt-test-002",
        contribution_weight=1.0,
        direction="long",
        confidence=75.0,
    ).model_dump(mode="json")
    db.append_event(
        event_type=EventType.SIGNAL_ACCEPTED_V1,
        payload=payload,
        source="test",
    )

    cfg = Config.from_repo_defaults(repo_root=Path(__file__).resolve().parents[2])
    cfg = cfg.model_copy(
        update={
            "data_dir": tmp_path / "data",
        }
    )

    identity = generate_node_identity()
    karma = KarmaEngine(config=cfg, db=db, identity=identity)

    # Check baseline karma (should not exist yet)
    baseline = db.conn.execute(
        "SELECT karma_score, win_count FROM producer_karma WHERE producer_id = ?",
        (producer_id,),
    ).fetchone()
    assert baseline is None, "Karma should not exist before position close"

    # attribute_outcome simulates what pnl.close_position() calls
    result = karma.attribute_outcome(
        trade_id=position_id,
        realized_pnl_usd=150.0,
    )

    assert result.get("producers_updated", 0) >= 1, (
        f"Producer karma not updated after position close. result={result}. Check that SIGNAL_ACCEPTED_V1 is emitted with position_id as trade_id."
    )

    # Verify karma row was created and win_count incremented
    updated = db.conn.execute(
        "SELECT karma_score, win_count, total_trades FROM producer_karma WHERE producer_id = ?",
        (producer_id,),
    ).fetchone()
    assert updated is not None, f"No karma row for producer {producer_id}"
    assert updated["win_count"] >= 1, f"Expected win_count >= 1, got {updated['win_count']}"
    assert updated["total_trades"] >= 1, f"Expected total_trades >= 1, got {updated['total_trades']}"
    # EMA update from 1.0 baseline with a positive outcome: 1.0 * 0.95 + 1.0 * 0.05 = 1.0 (no change in this case)
    # or any new karma value — just verify it's a valid float
    assert isinstance(float(updated["karma_score"]), float)

    # Verify ATTRIBUTION_OUTCOME_V1 event was emitted
    attr_events = [e for e in db.get_events(limit=50) if str(e.type) == str(EventType.ATTRIBUTION_OUTCOME_V1)]
    assert attr_events, "ATTRIBUTION_OUTCOME_V1 event not emitted after position close"
    attr_payload = attr_events[0].payload if isinstance(attr_events[0].payload, dict) else json.loads(attr_events[0].payload)
    assert attr_payload["trade_id"] == position_id, f"ATTRIBUTION_OUTCOME_V1 trade_id mismatch: got '{attr_payload['trade_id']}', expected '{position_id}'"


# ---------------------------------------------------------------------------
# Wave-1 Test 4: Only snapshot signals (source_event_ids) get credited
# ---------------------------------------------------------------------------


def test_only_snapshot_signals_get_accepted(tmp_path: Path) -> None:
    """Only the 2 source_event_ids from the intent appear in SIGNAL_ACCEPTED_V1 events.

    Regression for: OMS used to also query the DB for all recent signal.* events
    for the same symbol and merge them in — meaning producers got credit just for
    being recent, not for being in the synthesis snapshot.

    Fix: source_event_ids is the ONLY authoritative source.
    """
    db = Database(tmp_path / "db.sqlite")
    cfg = _karma_config(tmp_path)
    oms = _make_oms(tmp_path, cfg, db)

    # Insert 2 real signal events that WILL be in the intent snapshot
    ev1 = db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "BTC", "direction": "long", "confidence": 0.8},
        source="producer.ta",
    )
    ev2 = db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "BTC", "direction": "long", "confidence": 0.7},
        source="producer.momentum",
    )
    snapshot_ids = {ev1.id, ev2.id}

    # Insert an EXTRA signal event for the same symbol that was NOT in the snapshot
    ev_extra = db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "BTC", "direction": "long", "confidence": 0.6},
        source="producer.unrelated",
    )
    extra_id = ev_extra.id

    intent = TradeIntent(
        symbol="BTC",
        direction="long",
        size_pct=0.05,
        leverage=1.0,
        conviction_score=80.0,
        regime="BULL",
        rationale="wave-1 attribution truthfulness test",
        source_event_ids=list(snapshot_ids),
    )

    result = oms.submit(intent, mid_price=50_000.0, equity_usd=10_000.0)
    assert result.status == "filled", f"Unexpected OMS result: {result}"
    position_id = result.position_id

    # Collect all emitted SIGNAL_ACCEPTED_V1 signal_event_ids
    signal_accepted_events = [e for e in db.get_events(limit=200) if str(e.type) == str(EventType.SIGNAL_ACCEPTED_V1)]
    emitted_ids: set[str] = set()
    for ev in signal_accepted_events:
        payload = ev.payload if isinstance(ev.payload, dict) else json.loads(ev.payload)
        if payload.get("trade_id") == position_id:
            sig_id = payload.get("signal_event_id", "")
            if sig_id:
                emitted_ids.add(sig_id)

    # Exactly the 2 snapshot IDs must appear — no more, no less
    assert emitted_ids == snapshot_ids, (
        f"Expected exactly snapshot IDs {snapshot_ids}, got {emitted_ids}. Extra/unrelated ID {extra_id!r} must NOT be credited."
    )
    assert extra_id not in emitted_ids, f"Unrelated signal {extra_id!r} from 'producer.unrelated' was incorrectly credited."


# ---------------------------------------------------------------------------
# Wave-1 Test 5: Unrelated recent DB signals must NOT inflate the fallback
# ---------------------------------------------------------------------------


def test_unrelated_recent_signals_not_credited(tmp_path: Path) -> None:
    """When source_event_ids is empty, the fallback event uses producer_id='unknown'.

    Regression for: with the old DB-query path, even an empty source_event_ids
    would cause OMS to query the DB, find recent signals for the symbol, and emit
    SIGNAL_ACCEPTED_V1 events for those producers — giving undeserved credit.

    Fix: fallback must always use producer_id='unknown', never the DB signals.
    """
    db = Database(tmp_path / "db.sqlite")
    cfg = _karma_config(tmp_path)
    oms = _make_oms(tmp_path, cfg, db)

    # Insert 3 unrelated recent signal events for the same symbol
    for i in range(3):
        db.append_event(
            event_type=EventType.SIGNAL_TA_V1,
            payload={"symbol": "ETH", "direction": "long", "confidence": 0.7},
            source=f"producer.unrelated_{i}",
        )

    # Submit a trade with NO source_event_ids
    intent = TradeIntent(
        symbol="ETH",
        direction="long",
        size_pct=0.05,
        leverage=1.0,
        conviction_score=70.0,
        regime="BULL",
        rationale="wave-1 fallback test",
        source_event_ids=[],  # empty — forces fallback path
    )

    result = oms.submit(intent, mid_price=3_000.0, equity_usd=10_000.0)
    assert result.status == "filled", f"Unexpected OMS result: {result}"
    position_id = result.position_id

    # Collect all SIGNAL_ACCEPTED_V1 events for this trade
    signal_accepted_events = [e for e in db.get_events(limit=200) if str(e.type) == str(EventType.SIGNAL_ACCEPTED_V1)]
    trade_events = []
    for ev in signal_accepted_events:
        payload = ev.payload if isinstance(ev.payload, dict) else json.loads(ev.payload)
        if payload.get("trade_id") == position_id:
            trade_events.append(payload)

    assert trade_events, "Expected at least one SIGNAL_ACCEPTED_V1 fallback event"

    # Every fallback event must have producer_id='unknown'
    for payload in trade_events:
        assert payload.get("producer_id") == "unknown", (
            f"Fallback SIGNAL_ACCEPTED_V1 has producer_id={payload.get('producer_id')!r} "
            f"but expected 'unknown'. Unrelated DB signals must NOT inflate the fallback. "
            f"Full payload: {payload}"
        )

    # There must be no event crediting any of the unrelated producers
    credited_producers = {p.get("producer_id") for p in trade_events}
    for i in range(3):
        unrelated = f"producer.unrelated_{i}"
        assert unrelated not in credited_producers, f"Unrelated producer {unrelated!r} was incorrectly credited in fallback path."
