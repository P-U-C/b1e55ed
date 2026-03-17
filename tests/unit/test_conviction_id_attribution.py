"""Tests for conviction_id → close → karma attribution flywheel.

Verifies the full chain:
  TradeIntent.conviction_id → positions.conviction_id (INSERT)
  pnl.close_position() → karma.attribute_outcome() → ATTRIBUTION_OUTCOME_V1 emitted

Also covers the learning.run() backfill path for positions that were closed
before the karma attribution step succeeded (e.g. identity load failure).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType, SignalAcceptedPayload
from engine.execution.paper import PaperBroker
from engine.execution.pnl import PnLTracker
from engine.security.identity import generate_node_identity

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cfg(tmp_path: Path) -> Config:
    cfg = Config.from_repo_defaults(repo_root=Path(__file__).resolve().parents[2])
    return cfg.model_copy(update={"data_dir": tmp_path / "data"})


def _insert_conviction(db: Database, node_id: str, symbol: str = "BTC", direction: str = "long") -> int:
    """Insert a minimal conviction_scores row, return its id."""
    cur = db.execute(
        """INSERT INTO conviction_scores
               (cycle_id, node_id, symbol, direction, magnitude, timeframe, ts, commitment_hash, pcs_score, cts_score)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("cycle-test", node_id, symbol, direction, 7.5, "1d", "2026-01-01T00:00:00+00:00", "hash-test", 75.0, 0.8),
    )
    return cur.lastrowid  # type: ignore[return-value]


def _insert_signal_accepted(db: Database, trade_id: str, producer_id: str = "producer.ta", domain: str = "technical") -> None:
    payload = SignalAcceptedPayload(
        trade_id=trade_id,
        producer_id=producer_id,
        domain=domain,
        signal_event_id="evt-test-001",
        contribution_weight=1.0,
        direction="long",
        confidence=75.0,
    ).model_dump(mode="json")
    db.append_event(event_type=EventType.SIGNAL_ACCEPTED_V1, payload=payload, source="test")


# ---------------------------------------------------------------------------
# Test 1: conviction_id is persisted in the positions table on open
# ---------------------------------------------------------------------------


def test_conviction_id_written_to_positions_on_open(tmp_path: Path) -> None:
    """When PaperBroker.execute_market() receives conviction_id, it must be stored."""
    db = Database(tmp_path / "brain.db")
    ident = generate_node_identity()
    conv_id = _insert_conviction(db, node_id=ident.node_id)

    broker = PaperBroker(db)
    fill = broker.execute_market(
        symbol="BTC",
        direction="long",
        notional_usd=1000.0,
        leverage=1.0,
        mid_price=50_000.0,
        conviction_id=conv_id,
        pcs_at_entry=75.0,
        cts_at_entry=0.8,
    )

    row = db.fetchone("SELECT conviction_id FROM positions WHERE id = ?", (fill.position_id,))
    assert row is not None
    assert int(row["conviction_id"]) == conv_id


# ---------------------------------------------------------------------------
# Test 2: close_position emits ATTRIBUTION_OUTCOME_V1 when conviction_id is set
# ---------------------------------------------------------------------------


def test_close_position_emits_attribution_outcome_v1(tmp_path: Path) -> None:
    """Closing a position with conviction_id must fire ATTRIBUTION_OUTCOME_V1."""
    cfg = _cfg(tmp_path)
    db = Database(tmp_path / "brain.db")
    ident = generate_node_identity()
    conv_id = _insert_conviction(db, node_id=ident.node_id)

    broker = PaperBroker(db)
    fill = broker.execute_market(
        symbol="BTC",
        direction="long",
        notional_usd=1000.0,
        leverage=1.0,
        mid_price=50_000.0,
        conviction_id=conv_id,
        pcs_at_entry=75.0,
    )

    # Wire a SIGNAL_ACCEPTED_V1 so karma has something to attribute
    _insert_signal_accepted(db, trade_id=fill.position_id, producer_id="test.producer")

    pnl = PnLTracker(db, config=cfg)
    realized = pnl.close_position(position_id=fill.position_id, exit_price=55_000.0)
    assert realized > 0

    # conviction_id must still be on the closed position
    row = db.fetchone("SELECT conviction_id, status FROM positions WHERE id = ?", (fill.position_id,))
    assert row is not None
    assert str(row["status"]) == "closed"
    assert int(row["conviction_id"]) == conv_id

    # ATTRIBUTION_OUTCOME_V1 must have been emitted
    events = db.get_events(event_type=EventType.ATTRIBUTION_OUTCOME_V1, limit=10)
    assert events, "ATTRIBUTION_OUTCOME_V1 was not emitted after position close"

    ev = events[0]
    assert ev.payload["trade_id"] == fill.position_id
    assert ev.payload["realized_pnl_usd"] == pytest.approx(realized, rel=1e-3)
    assert len(ev.payload["producers"]) >= 1
    assert ev.payload["producers"][0]["producer_id"] == "test.producer"


# ---------------------------------------------------------------------------
# Test 3: learning.run() backfills karma for positions missed on close
# ---------------------------------------------------------------------------


def test_learning_run_backfills_missed_karma_attribution(tmp_path: Path) -> None:
    """If a position was closed but karma attribution was never emitted,
    learning.run() must backfill ATTRIBUTION_OUTCOME_V1."""
    from engine.brain.learning import LearningLoop

    cfg = _cfg(tmp_path)
    db = Database(tmp_path / "brain.db")
    ident = generate_node_identity()
    conv_id = _insert_conviction(db, node_id=ident.node_id)

    broker = PaperBroker(db)
    fill = broker.execute_market(
        symbol="ETH",
        direction="long",
        notional_usd=500.0,
        leverage=1.0,
        mid_price=2000.0,
        conviction_id=conv_id,
    )

    # Add a signal so attribute_outcome has something to match
    _insert_signal_accepted(db, trade_id=fill.position_id, producer_id="test.producer.backfill")

    # Manually close position WITHOUT going through PnLTracker (simulates a crash
    # between the DB update and the karma call in pnl.close_position)
    from engine.core.time import utc_now

    db.execute(
        "UPDATE positions SET status = 'closed', closed_at = ?, realized_pnl = ? WHERE id = ?",
        (utc_now().isoformat(), 50.0, fill.position_id),
    )

    # Confirm no ATTRIBUTION_OUTCOME_V1 yet
    before = db.get_events(event_type=EventType.ATTRIBUTION_OUTCOME_V1, limit=10)
    assert not before, "Expected no ATTRIBUTION_OUTCOME_V1 before learning.run()"

    # learning.run() should backfill
    loop = LearningLoop(db=db, config=cfg)
    loop.run()

    # Verify ATTRIBUTION_OUTCOME_V1 was emitted by the backfill
    after = db.get_events(event_type=EventType.ATTRIBUTION_OUTCOME_V1, limit=10)
    assert after, "learning.run() must backfill ATTRIBUTION_OUTCOME_V1 for missed positions"

    ev = after[0]
    assert ev.payload["trade_id"] == fill.position_id


# ---------------------------------------------------------------------------
# Test 4: learning.run() backfill is idempotent (second run doesn't double-emit)
# ---------------------------------------------------------------------------


def test_learning_run_backfill_is_idempotent(tmp_path: Path) -> None:
    """Calling learning.run() twice must not emit duplicate ATTRIBUTION_OUTCOME_V1."""
    from engine.brain.learning import LearningLoop

    cfg = _cfg(tmp_path)
    db = Database(tmp_path / "brain.db")
    ident = generate_node_identity()
    conv_id = _insert_conviction(db, node_id=ident.node_id)

    broker = PaperBroker(db)
    fill = broker.execute_market(
        symbol="SOL",
        direction="long",
        notional_usd=300.0,
        leverage=1.0,
        mid_price=100.0,
        conviction_id=conv_id,
    )
    _insert_signal_accepted(db, trade_id=fill.position_id, producer_id="test.idempotent")

    from engine.core.time import utc_now

    db.execute(
        "UPDATE positions SET status = 'closed', closed_at = ?, realized_pnl = ? WHERE id = ?",
        (utc_now().isoformat(), 10.0, fill.position_id),
    )

    loop = LearningLoop(db=db, config=cfg)
    loop.run()
    loop.run()  # second run must not duplicate

    events = db.get_events(event_type=EventType.ATTRIBUTION_OUTCOME_V1, limit=20)
    assert len(events) == 1, f"Expected exactly 1 ATTRIBUTION_OUTCOME_V1, got {len(events)}"
