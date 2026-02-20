"""Tests for event replay, integrity checking, and projection determinism (R1)."""

from __future__ import annotations

import json

from engine.core.database import Database
from engine.core.events import EventType
from engine.core.projections import ProjectionManager


def _make_db(tmp_path):
    db = Database(db_path=str(tmp_path / "test.db"))
    return db


def test_iter_events_ascending_returns_all(tmp_path):
    db = _make_db(tmp_path)
    ids = []
    for i in range(5):
        ev = db.append_event(
            event_type=EventType.SIGNAL_TA_V1,
            payload={"symbol": "BTC", "score": i},
            source="test",
        )
        ids.append(ev.id)
    events = db.iter_events_ascending()
    assert len(events) == 5
    assert [e.id for e in events] == ids
    db.close()


def test_iter_events_ascending_with_range(tmp_path):
    db = _make_db(tmp_path)
    ids = []
    for i in range(5):
        ev = db.append_event(
            event_type=EventType.SIGNAL_TA_V1,
            payload={"symbol": "BTC", "score": i},
            source="test",
        )
        ids.append(ev.id)
    # from_id to to_id inclusive
    events = db.iter_events_ascending(from_id=ids[1], to_id=ids[3])
    assert len(events) == 3
    assert events[0].id == ids[1]
    assert events[-1].id == ids[3]
    db.close()


def test_iter_events_ascending_with_type_filter(tmp_path):
    db = _make_db(tmp_path)
    db.append_event(event_type=EventType.SIGNAL_TA_V1, payload={"symbol": "BTC"}, source="test")
    db.append_event(event_type=EventType.KILL_SWITCH_V1, payload={"level": "SAFE"}, source="test")
    db.append_event(event_type=EventType.SIGNAL_TA_V1, payload={"symbol": "ETH"}, source="test")

    signals = db.iter_events_ascending(event_type=EventType.SIGNAL_TA_V1)
    assert len(signals) == 2
    db.close()


def test_projection_rebuild_deterministic(tmp_path):
    """Replaying the same events twice produces identical projection state."""
    db = _make_db(tmp_path)
    for sym in ["BTC", "ETH", "SOL"]:
        db.append_event(
            event_type=EventType.SIGNAL_TA_V1,
            payload={"symbol": sym, "score": 7, "direction": "bullish"},
            source="test",
        )

    events = db.iter_events_ascending()

    pm1 = ProjectionManager()
    pm1.rebuild(events)
    state1 = pm1.get_state()

    pm2 = ProjectionManager()
    pm2.rebuild(events)
    state2 = pm2.get_state()

    assert json.dumps(state1, sort_keys=True, default=str) == json.dumps(state2, sort_keys=True, default=str)
    db.close()


def test_projection_rebuild_from_empty(tmp_path):
    """Rebuilding with no events produces empty projections."""
    db = _make_db(tmp_path)
    events = db.iter_events_ascending()
    assert events == []

    pm = ProjectionManager()
    pm.rebuild(events)
    state = pm.get_state()
    # Core projections should be empty (regime may have defaults)
    assert len(state["signals_latest"]) == 0
    assert len(state["position_conviction"].get("by_position", state["position_conviction"])) == 0
    assert len(state["position_state"].get("positions", state["position_state"])) == 0
    # outcomes may be a dict with sub-keys; check the actual data is empty
    outcomes = state.get("outcomes", {})
    if isinstance(outcomes, dict) and "outcomes" in outcomes:
        assert len(outcomes["outcomes"]) == 0
    else:
        assert len(outcomes) == 0
    db.close()


def test_hash_chain_integrity_after_replay(tmp_path):
    """Hash chain remains valid after multiple appends."""
    db = _make_db(tmp_path)
    for i in range(10):
        db.append_event(
            event_type=EventType.SIGNAL_TA_V1,
            payload={"symbol": "BTC", "round": i},
            source="test",
        )
    assert db.verify_hash_chain() is True
    db.close()


def test_detect_concurrent_writers_single_process(tmp_path):
    """Single writer should not detect concurrency."""
    db = _make_db(tmp_path)
    assert db.detect_concurrent_writers() is False
    db.close()


def test_last_hash_read_from_db_not_cache(tmp_path):
    """_last_hash is re-read from DB inside append, not just cached."""
    db = _make_db(tmp_path)
    ev1 = db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "BTC"},
        source="test",
    )
    # Tamper with cache (simulating stale state)
    db._last_hash = "stale_hash_that_should_be_overwritten"

    # Next append should read from DB, not use stale cache
    ev2 = db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "ETH"},
        source="test",
    )
    # Chain should still be valid because we read from DB
    assert db.verify_hash_chain() is True
    assert ev2.prev_hash == ev1.hash
    db.close()


def test_cli_replay_json(tmp_path, monkeypatch):
    """CLI replay command produces valid JSON output."""
    from engine.cli import main

    # Create data dir and seed DB
    (tmp_path / "data").mkdir()
    db = Database(db_path=str(tmp_path / "data" / "brain.db"))
    db.append_event(event_type=EventType.SIGNAL_TA_V1, payload={"symbol": "BTC"}, source="test")
    db.close()

    # CLI reads repo_root from cwd
    monkeypatch.chdir(tmp_path)

    import io
    import sys

    captured = io.StringIO()
    monkeypatch.setattr(sys, "stdout", captured)

    rc = main(["replay", "--json"])
    assert rc == 0
    output = json.loads(captured.getvalue())
    assert output["status"] == "ok"
    assert output["events_replayed"] == 1


def test_cli_integrity_json(tmp_path, monkeypatch):
    """CLI integrity command produces valid JSON output."""
    from engine.cli import main

    (tmp_path / "data").mkdir()
    db = Database(db_path=str(tmp_path / "data" / "brain.db"))
    db.append_event(event_type=EventType.SIGNAL_TA_V1, payload={"symbol": "BTC"}, source="test")
    db.close()

    monkeypatch.chdir(tmp_path)

    import io
    import sys

    captured = io.StringIO()
    monkeypatch.setattr(sys, "stdout", captured)

    rc = main(["integrity", "--json"])
    assert rc == 0
    output = json.loads(captured.getvalue())
    assert output["status"] == "ok"
    assert output["checks"]["hash_chain"] == "pass"
    assert output["checks"]["projection_determinism"] == "pass"
    assert output["checks"]["single_writer"] == "pass"
