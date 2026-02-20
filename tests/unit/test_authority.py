"""Tests for authority model and write-lock enforcement (A1)."""

from __future__ import annotations

import sqlite3
import threading

from engine.core.database import Database
from engine.core.events import EventType


def _make_db(tmp_path):
    return Database(db_path=str(tmp_path / "test.db"))


def test_single_writer_no_conflict(tmp_path):
    """Single writer appends without issues."""
    db = _make_db(tmp_path)
    ev = db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "BTC"},
        source="test",
    )
    assert ev.hash is not None
    assert db.verify_hash_chain() is True
    db.close()


def test_concurrent_threads_serialized(tmp_path):
    """Multiple threads writing are serialized by the RLock."""
    db = _make_db(tmp_path)
    errors = []

    def writer(n):
        try:
            for i in range(5):
                db.append_event(
                    event_type=EventType.SIGNAL_TA_V1,
                    payload={"symbol": "BTC", "thread": n, "i": i},
                    source="test",
                )
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Errors during concurrent writes: {errors}"
    assert db.verify_hash_chain() is True

    events = db.iter_events_ascending()
    assert len(events) == 15  # 3 threads × 5 events
    db.close()


def test_hash_chain_detects_tampering(tmp_path):
    """Modifying an event's payload breaks the hash chain."""
    db = _make_db(tmp_path)
    for i in range(3):
        db.append_event(
            event_type=EventType.SIGNAL_TA_V1,
            payload={"symbol": "BTC", "i": i},
            source="test",
        )

    # Tamper with middle event
    db.conn.execute('UPDATE events SET payload = \'{"symbol": "TAMPERED"}\' WHERE rowid = 2')

    assert db.verify_hash_chain() is False
    db.close()


def test_cross_process_writer_detection(tmp_path):
    """Detect when another connection holds a write lock."""
    db_path = str(tmp_path / "test.db")
    db = Database(db_path=db_path)
    db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "BTC"},
        source="test",
    )

    # Open second connection and hold a write lock
    conn2 = sqlite3.connect(db_path)
    conn2.execute("BEGIN IMMEDIATE")

    # Now the primary should detect concurrent writer
    assert db.detect_concurrent_writers() is True

    conn2.execute("ROLLBACK")
    conn2.close()

    # After release, no concurrent writer
    assert db.detect_concurrent_writers() is False
    db.close()


def test_prev_hash_read_inside_transaction(tmp_path):
    """prev_hash is read from DB, not stale cache, on each append."""
    db = _make_db(tmp_path)

    ev1 = db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "BTC"},
        source="test",
    )

    # Corrupt the cache
    db._last_hash = "corrupted_cache_value"

    ev2 = db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "ETH"},
        source="test",
    )

    # ev2 should chain from ev1, not from corrupted cache
    assert ev2.prev_hash == ev1.hash
    assert db.verify_hash_chain() is True
    db.close()


def test_batch_append_atomic(tmp_path):
    """Batch append is atomic — all or nothing."""
    db = _make_db(tmp_path)

    # Successful batch
    events = db.append_events_batch(
        [
            (EventType.SIGNAL_TA_V1, {"symbol": "BTC"}, None),
            (EventType.SIGNAL_TA_V1, {"symbol": "ETH"}, None),
            (EventType.SIGNAL_TA_V1, {"symbol": "SOL"}, None),
        ],
        source="test",
    )
    assert len(events) == 3
    assert db.verify_hash_chain() is True
    db.close()
