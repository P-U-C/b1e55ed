"""Tests for prune_old_data() retention/pruning bug fixes.

Covers three bugs:
1. conviction_scores.created_at column was missing — migration must add it.
2. api_rate_limits.window_start is stored as integer epoch, not datetime text.
3. Events pruning must clean event_dedup (FK child) before events (FK parent).
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from engine.core.database import Database
from engine.core.events import EventType


class _RetentionConfig:
    """Minimal retention config for tests — no vacuum so tests stay fast."""

    enabled = True
    events_keep_days = 7
    conviction_log_keep_days = 30
    feature_snapshots_keep_days = 7
    api_rate_limits_keep_hours = 1
    vacuum_on_prune = False


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    return Database(db_path=tmp_path / "test.db")


# ---------------------------------------------------------------------------
# Bug 1 — conviction_scores.created_at migration
# ---------------------------------------------------------------------------


def test_prune_conviction_scores_does_not_reference_missing_column(db: Database) -> None:
    """conviction_scores.created_at must be added by migration and usable in prune."""
    # Verify the column exists after migration
    cols = [str(r[1]) for r in db.conn.execute("PRAGMA table_info(conviction_scores)").fetchall()]
    assert "created_at" in cols, "Migration must add created_at to conviction_scores"

    # Insert a resolved conviction score with an old created_at to be prunable
    db.conn.execute(
        """
        INSERT INTO conviction_scores
            (node_id, symbol, direction, magnitude, timeframe, ts, commitment_hash,
             outcome, created_at)
        VALUES
            ('test_node', 'BTCUSDT', 'long', 7.5, '1h', datetime('now'),
             'deadbeef', 1.0, datetime('now', '-60 days'))
        """
    )
    db.conn.commit()

    retention = _RetentionConfig()
    # Must not raise OperationalError: "no such column: created_at"
    result = db.prune_old_data(retention)

    assert result.get("conviction_scores", 0) >= 1, "prune_old_data should have deleted the old resolved conviction score"


# ---------------------------------------------------------------------------
# Bug 2 — api_rate_limits epoch comparison
# ---------------------------------------------------------------------------


def test_prune_api_rate_limits_uses_epoch_logic(db: Database) -> None:
    """api_rate_limits pruning must use integer epoch arithmetic, not datetime text."""
    now_epoch = int(time.time())
    old_epoch = now_epoch - (3 * 3600)  # 3 hours ago → older than 1 h retention
    recent_epoch = now_epoch - (10 * 60)  # 10 minutes ago → within retention window

    db.conn.execute(
        "INSERT INTO api_rate_limits (key, window_start, window_seconds, count) VALUES ('old_window', ?, 60, 5)",
        (old_epoch,),
    )
    db.conn.execute(
        "INSERT INTO api_rate_limits (key, window_start, window_seconds, count) VALUES ('recent_window', ?, 60, 3)",
        (recent_epoch,),
    )
    db.conn.commit()

    retention = _RetentionConfig()
    result = db.prune_old_data(retention)

    assert result.get("api_rate_limits", 0) >= 1, "prune_old_data should have deleted the old rate-limit window"

    old_row = db.conn.execute("SELECT * FROM api_rate_limits WHERE key = 'old_window'").fetchone()
    assert old_row is None, "old_window (3 h ago) must be pruned"

    recent_row = db.conn.execute("SELECT * FROM api_rate_limits WHERE key = 'recent_window'").fetchone()
    assert recent_row is not None, "recent_window (10 min ago) must survive pruning"


# ---------------------------------------------------------------------------
# Bug 3 — event_dedup FK violation ordering
# ---------------------------------------------------------------------------


def test_prune_events_cleans_event_dedup_first(db: Database) -> None:
    """Pruning events must delete from event_dedup before events to avoid FK violations."""
    # Append an event with a dedupe_key → inserts a row into event_dedup
    event = db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "BTCUSDT", "rsi_14": 42.0},
        dedupe_key="prune_test_dedup_key",
    )

    # Back-date created_at so the retention window triggers deletion
    db.conn.execute(
        "UPDATE events SET created_at = datetime('now', '-60 days') WHERE id = ?",
        (event.id,),
    )
    db.conn.commit()

    # Confirm event_dedup row exists before pruning
    dedup_before = db.conn.execute("SELECT * FROM event_dedup WHERE event_id = ?", (event.id,)).fetchone()
    assert dedup_before is not None, "event_dedup row must exist before pruning"

    retention = _RetentionConfig()
    # Must not raise "FOREIGN KEY constraint failed"
    result = db.prune_old_data(retention)

    assert result.get("events", 0) >= 1, "prune_old_data should have deleted the old event"

    # event_dedup row must have been cleaned up as well
    dedup_after = db.conn.execute("SELECT * FROM event_dedup WHERE event_id = ?", (event.id,)).fetchone()
    assert dedup_after is None, "event_dedup row must be deleted before events to satisfy FK constraint"
