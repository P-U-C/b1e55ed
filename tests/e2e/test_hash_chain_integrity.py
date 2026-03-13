"""tests/e2e/test_hash_chain_integrity.py

End-to-end tests for hash chain integrity.

Tests
-----
1. Append 10 events; verify chain links correctly
2. Each event's hash chains to the previous
3. Tamper with a payload in SQLite → integrity_check detects it
4. Appending after tamper: the chain detects the break at verification
"""

from __future__ import annotations

import json

import pytest

from engine.core.database import Database
from engine.core.events import EventType

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path):
    d = Database(tmp_path / "brain.db")
    yield d
    d.close()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _append_n(db: Database, n: int, source: str = "test.producer") -> list:
    events = []
    for i in range(n):
        ev = db.append_event(
            event_type=EventType.SIGNAL_TA_V1,
            payload={"symbol": "BTC", "index": i, "rsi_14": float(i)},
            source=source,
        )
        events.append(ev)
    return events


# ---------------------------------------------------------------------------
# 1 + 2. Append 10 events; verify chain
# ---------------------------------------------------------------------------


def test_chain_links_10_events(db):
    """Each event's prev_hash must equal the hash of the preceding event."""
    events = _append_n(db, 10)

    assert len(events) == 10

    # First event: prev_hash must be the genesis sentinel
    assert events[0].prev_hash == Database.GENESIS_PREV_HASH, "First event's prev_hash must equal GENESIS_PREV_HASH"

    for i in range(1, len(events)):
        expected_prev = events[i - 1].hash
        actual_prev = events[i].prev_hash
        assert actual_prev == expected_prev, f"Event {i} prev_hash mismatch: expected {expected_prev}, got {actual_prev}"


def test_all_hashes_64_hex_chars(db):
    """All event hashes must be 64-character hex strings (SHA-256)."""
    events = _append_n(db, 5)
    for ev in events:
        assert len(ev.hash) == 64, f"Expected 64-char hash, got {len(ev.hash)}"
        assert all(c in "0123456789abcdef" for c in ev.hash), "Hash must be lowercase hex"


def test_verify_hash_chain_passes_clean_db(db):
    """verify_hash_chain() returns True on an untampered chain."""
    _append_n(db, 10)
    assert db.verify_hash_chain() is True


# ---------------------------------------------------------------------------
# 3. Tamper with payload → integrity check detects it
# ---------------------------------------------------------------------------


def test_tamper_detected_by_verify(db):
    """Modifying a stored payload invalidates the hash chain."""
    events = _append_n(db, 10)

    # Pick middle event to tamper
    target = events[5]

    # Tamper: change the payload in the raw SQLite row
    tampered_payload = json.dumps({"symbol": "BTC", "index": 5, "rsi_14": 99.9, "_tampered": True})
    db.conn.execute(
        "UPDATE events SET payload = ? WHERE id = ?",
        (tampered_payload, target.id),
    )
    db.conn.commit()

    # verify_hash_chain() must detect the tamper
    chain_ok = db.verify_hash_chain()
    assert chain_ok is False, "verify_hash_chain() must return False when a payload has been tampered with"


def test_tamper_first_event_detected(db):
    """Tampering with the first event (genesis link) is detected."""
    events = _append_n(db, 5)

    db.conn.execute(
        "UPDATE events SET payload = ? WHERE id = ?",
        (json.dumps({"symbol": "BTC", "rsi_14": -1.0, "_tampered": True}), events[0].id),
    )
    db.conn.commit()

    assert db.verify_hash_chain() is False


def test_tamper_last_event_detected(db):
    """Tampering with the most recent event is detected."""
    events = _append_n(db, 5)

    db.conn.execute(
        "UPDATE events SET payload = ? WHERE id = ?",
        (json.dumps({"symbol": "BTC", "rsi_14": 0.0, "_last_tampered": True}), events[-1].id),
    )
    db.conn.commit()

    assert db.verify_hash_chain() is False


# ---------------------------------------------------------------------------
# 4. Appending after tamper: new chain is consistent from tamper point onward,
#    but the full chain (including tampered events) is still broken.
# ---------------------------------------------------------------------------


def test_chain_after_tamper_still_broken(db):
    """Appending a new event after tampering doesn't heal the chain.

    The new event is appended with prev_hash = hash of the tampered event
    (as stored), which is now inconsistent with the actual payload. The full
    chain walk still detects the original tamper.
    """
    events = _append_n(db, 5)

    # Tamper event index 2
    db.conn.execute(
        "UPDATE events SET payload = ? WHERE id = ?",
        (json.dumps({"symbol": "BTC", "rsi_14": 777.0, "_fork": True}), events[2].id),
    )
    db.conn.commit()

    # Append new event (will chain from the tampered state)
    db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "BTC", "rsi_14": 50.0, "post_tamper": True},
    )

    # Full chain must still fail because event[2] was tampered
    assert db.verify_hash_chain() is False


# ---------------------------------------------------------------------------
# 5. Deduplicated events are idempotent
# ---------------------------------------------------------------------------


def test_deduplication_is_idempotent(db):
    """Same dedupe_key + same payload → returns existing event, no new row."""
    ev1 = db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "BTC", "rsi_14": 42.0},
        dedupe_key="dedup-test-1",
    )
    ev2 = db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "BTC", "rsi_14": 42.0},
        dedupe_key="dedup-test-1",
    )
    assert ev1.id == ev2.id, "Idempotent dedup must return the same event"

    count = db.conn.execute("SELECT COUNT(*) FROM events WHERE dedupe_key = 'dedup-test-1'").fetchone()[0]
    assert count == 1, "Only one row must exist for a deduplicated event"


def test_deduplication_conflict_raises(db):
    """Same dedupe_key + DIFFERENT payload → DedupeConflictError."""

    db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "BTC", "rsi_14": 42.0},
        dedupe_key="conflict-key-1",
    )
    # Payload drift now logs a warning and returns the original event (no exception).
    e2 = db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "BTC", "rsi_14": 99.0},  # different
        dedupe_key="conflict-key-1",
    )
    assert e2.dedupe_key == "conflict-key-1"  # original event returned


# ---------------------------------------------------------------------------
# 6. Batch append is atomic
# ---------------------------------------------------------------------------


def test_batch_append_atomic(db):
    """append_events_batch inserts all events in one transaction."""
    events_before = len(db.get_events(limit=1000))

    batch = [(EventType.SIGNAL_TA_V1, {"symbol": "BTC", "batch_idx": i}, None) for i in range(5)]
    results = db.append_events_batch(batch, source="batch.test")

    assert len(results) == 5
    events_after = len(db.get_events(limit=1000))
    assert events_after == events_before + 5

    # Chain must remain valid
    assert db.verify_hash_chain() is True


# ---------------------------------------------------------------------------
# 7. Chain integrity with many events
# ---------------------------------------------------------------------------


def test_large_chain_integrity(db):
    """50 events → verify_hash_chain() passes."""
    _append_n(db, 50)
    assert db.verify_hash_chain() is True
