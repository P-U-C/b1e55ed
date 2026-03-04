"""Tests for flywheel S2: karma attribution wiring.

Covers:
- close_position DB updates
- double-close raises ValueError
- attribute_outcome positive → karma increases
- attribute_outcome negative → loss tracked, karma unchanged
- attribute_outcome no signals → no-op
- karma failure non-blocking (OMS still completes)
- ATTRIBUTION_OUTCOME_V1 event emitted
- karma weights loaded in synthesis
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType, SignalAcceptedPayload
from engine.execution.karma import KarmaEngine
from engine.execution.paper import PaperBroker
from engine.execution.pnl import PnLTracker
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
    execution = c.execution.model_copy(update={"mode": "paper"})
    return c.model_copy(update={"data_dir": tmp_path / "data", "karma": karma, "execution": execution})


def _make_position(db: Database) -> tuple[str, str]:
    """Create a paper position and return (position_id, order_id)."""
    broker = PaperBroker(db)
    fill = broker.execute_market(
        symbol="BTC",
        direction="long",
        notional_usd=1000.0,
        leverage=1.0,
        mid_price=50_000.0,
    )
    return fill.position_id, fill.order_id


def _insert_signal_accepted(db: Database, trade_id: str, producer_id: str = "producer.ta", domain: str = "technical") -> None:
    """Insert a SIGNAL_ACCEPTED_V1 event for the given trade_id."""
    payload = SignalAcceptedPayload(
        trade_id=trade_id,
        producer_id=producer_id,
        domain=domain,
        signal_event_id="evt-dummy-123",
        contribution_weight=1.0,
        direction="long",
        confidence=75.0,
    ).model_dump(mode="json")

    db.append_event(
        event_type=EventType.SIGNAL_ACCEPTED_V1,
        payload=payload,
        source="test",
    )


# ------------------------------------------------------------------
# Test 1: close_position updates DB
# ------------------------------------------------------------------


def test_close_position_updates_db(tmp_path: Path) -> None:
    db = Database(tmp_path / "db.sqlite")
    pnl = PnLTracker(db)
    pos_id, _ = _make_position(db)

    realized = pnl.close_position(position_id=pos_id, exit_price=55_000.0)
    assert realized > 0

    row = db.conn.execute("SELECT status, realized_pnl, closed_at FROM positions WHERE id = ?", (pos_id,)).fetchone()
    assert row is not None
    assert str(row[0]) == "closed"
    assert float(row[1]) > 0
    assert row[2] is not None  # closed_at is set


# ------------------------------------------------------------------
# Test 2: double-close raises ValueError
# ------------------------------------------------------------------


def test_close_position_raises_if_already_closed(tmp_path: Path) -> None:
    db = Database(tmp_path / "db.sqlite")
    pnl = PnLTracker(db)
    pos_id, _ = _make_position(db)

    pnl.close_position(position_id=pos_id, exit_price=55_000.0)
    with pytest.raises(ValueError, match="not open"):
        pnl.close_position(position_id=pos_id, exit_price=55_000.0)


# ------------------------------------------------------------------
# Test 3: karma attribute_outcome positive → karma increases
# ------------------------------------------------------------------


def test_karma_attribute_outcome_positive(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    db = Database(tmp_path / "db.sqlite")
    ident = generate_node_identity()

    pos_id, order_id = _make_position(db)
    _insert_signal_accepted(db, trade_id=order_id, producer_id="producer.ta", domain="technical")

    karma = KarmaEngine(config=cfg, db=db, identity=ident)
    result = karma.attribute_outcome(trade_id=order_id, realized_pnl_usd=100.0)

    assert result != {}
    assert result["outcome"] == 1.0
    assert result["producers_updated"] >= 1

    # Check producer_karma table
    row = db.conn.execute("SELECT karma_score, win_count, total_trades FROM producer_karma WHERE producer_id = ?", ("producer.ta",)).fetchone()
    assert row is not None
    # EMA: 1.0 * 0.95 + 1.0 * 0.05 = 1.0 (stays at 1.0 since default equals target)
    assert float(row[0]) >= 1.0
    assert int(row[1]) == 1  # win_count
    assert int(row[2]) == 1  # total_trades


# ------------------------------------------------------------------
# Test 4: negative outcome → loss tracked, karma unchanged
# ------------------------------------------------------------------


def test_karma_attribute_outcome_negative_tracked_not_applied(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    db = Database(tmp_path / "db.sqlite")
    ident = generate_node_identity()

    pos_id, order_id = _make_position(db)
    _insert_signal_accepted(db, trade_id=order_id, producer_id="producer.onchain", domain="onchain")

    karma = KarmaEngine(config=cfg, db=db, identity=ident)
    result = karma.attribute_outcome(trade_id=order_id, realized_pnl_usd=-50.0)

    assert result["outcome"] == -1.0

    row = db.conn.execute("SELECT karma_score, loss_count, win_count FROM producer_karma WHERE producer_id = ?", ("producer.onchain",)).fetchone()
    assert row is not None
    assert float(row[0]) == 1.0  # karma unchanged (Phase 0: losses not applied)
    assert int(row[1]) == 1  # loss_count incremented
    assert int(row[2]) == 0  # no wins


# ------------------------------------------------------------------
# Test 5: no signals → no-op
# ------------------------------------------------------------------


def test_karma_attribute_outcome_no_signals_is_noop(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    db = Database(tmp_path / "db.sqlite")
    ident = generate_node_identity()

    karma = KarmaEngine(config=cfg, db=db, identity=ident)
    result = karma.attribute_outcome(trade_id="nonexistent-trade", realized_pnl_usd=100.0)

    assert result == {}

    # No crash, no producer_karma rows
    rows = db.conn.execute("SELECT COUNT(*) FROM producer_karma").fetchone()
    assert int(rows[0]) == 0


# ------------------------------------------------------------------
# Test 6: karma failure non-blocking
# ------------------------------------------------------------------


def test_karma_failure_nonblocking(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    db = Database(tmp_path / "db.sqlite")
    ident = generate_node_identity()

    karma = KarmaEngine(config=cfg, db=db, identity=ident)

    # Simulate failure by patching _db to a broken object
    class BrokenConn:  # noqa: N801
        @staticmethod
        def execute(*args, **kwargs):
            raise RuntimeError("simulated DB crash")

    class BrokenDB:
        conn = BrokenConn()

    original_db = karma._db
    karma._db = BrokenDB()  # type: ignore[assignment]

    # Should NOT raise — non-blocking contract
    result = karma.attribute_outcome(trade_id="crash-trade", realized_pnl_usd=100.0)

    karma._db = original_db  # restore

    # Returns empty dict on failure
    assert result == {}


# ------------------------------------------------------------------
# Test 7: ATTRIBUTION_OUTCOME_V1 event emitted
# ------------------------------------------------------------------


def test_attribution_outcome_event_emitted(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    db = Database(tmp_path / "db.sqlite")
    ident = generate_node_identity()

    pos_id, order_id = _make_position(db)
    _insert_signal_accepted(db, trade_id=order_id, producer_id="producer.social", domain="social")

    karma = KarmaEngine(config=cfg, db=db, identity=ident)
    karma.attribute_outcome(trade_id=order_id, realized_pnl_usd=50.0)

    # Check events table for ATTRIBUTION_OUTCOME_V1
    events = db.get_events(event_type=EventType.ATTRIBUTION_OUTCOME_V1, limit=10)
    assert len(events) >= 1

    ev = events[0]
    assert ev.payload["trade_id"] == order_id
    assert ev.payload["realized_pnl_usd"] == 50.0
    assert len(ev.payload["producers"]) >= 1
    assert ev.payload["producers"][0]["producer_id"] == "producer.social"


# ------------------------------------------------------------------
# Test 8: karma weights loaded in synthesis
# ------------------------------------------------------------------


def test_karma_weights_loaded_in_synthesis(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    db = Database(tmp_path / "db.sqlite")

    # Insert producer_karma entries
    db.conn.execute(
        "INSERT INTO producer_karma (producer_id, karma_score, win_count, loss_count, total_trades, last_updated) VALUES (?, ?, ?, ?, ?, ?)",
        ("producer.ta", 1.5, 10, 2, 12, "2026-01-01T00:00:00+00:00"),
    )
    db.conn.commit()

    # Insert a SIGNAL_ACCEPTED_V1 to map producer.ta -> technical domain
    _insert_signal_accepted(db, trade_id="t-synth", producer_id="producer.ta", domain="technical")

    from engine.brain.synthesis import VectorSynthesis

    synth = VectorSynthesis(cfg, db)
    multipliers = synth._load_karma_multipliers()

    assert "technical" in multipliers
    assert multipliers["technical"] == 1.5  # karma_score for producer.ta
