"""Unit tests for SPI lifecycle state machine and slash conditions (Phase 2B).

Tests cover:
- Valid lifecycle transitions
- Invalid transition raises ValueError
- retired state has no valid transitions
- check_promotion_criteria for onboarding→shadow and shadow→active
- maybe_auto_promote eligible and ineligible
- karma_floor slash condition
- signal_spam slash condition
- apply_slash warn (logs only) and suspend (transitions state)
- Full flow: register → accept 5 signals → auto-promote to shadow
"""

from __future__ import annotations

import contextlib
import sqlite3
from datetime import datetime, timedelta

import pytest

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from engine.spi.admission import _ensure_tables, accept_signal
from engine.spi.lifecycle import (
    VALID_TRANSITIONS,
    check_promotion_criteria,
    get_producer,
    maybe_auto_promote,
    transition,
)
from engine.spi.slash import (
    _check_karma_floor,
    _check_signal_spam,
    apply_slash,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _DB:
    """Minimal in-memory SQLite wrapper matching engine.core.database.Database API."""

    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def fetchone(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()


def _setup_db() -> _DB:
    db = _DB()
    _ensure_tables(db)
    # Ensure api_key_hash column exists (needed for registration in full-flow test)
    with contextlib.suppress(Exception):
        db.execute("ALTER TABLE spi_producers ADD COLUMN api_key_hash TEXT")
    return db


def _register_producer(db: _DB, producer_id: str, state: str = "onboarding") -> None:
    now = datetime.now(tz=UTC).isoformat()
    db.execute(
        """
        INSERT OR IGNORE INTO spi_producers
            (producer_id, producer_name, lifecycle_state, ingress_mode,
             registered_at, created_at, updated_at)
        VALUES (?, ?, ?, 'native', ?, ?, ?)
        """,
        (producer_id, producer_id, state, now, now, now),
    )


def _insert_karma(db: _DB, producer_id: str, epoch: int, running_karma: float) -> None:
    now = datetime.now(tz=UTC).isoformat()
    db.execute(
        """
        INSERT OR REPLACE INTO spi_karma
            (producer_id, epoch, epoch_brier, epoch_karma, running_karma, resolved_count, updated_at)
        VALUES (?, ?, NULL, NULL, ?, 0, ?)
        """,
        (producer_id, epoch, running_karma, now),
    )


def _insert_signal(
    db: _DB,
    producer_id: str,
    status: str = "accepted",
    submitted_at: str | None = None,
) -> None:
    import uuid

    now = submitted_at or datetime.now(tz=UTC).isoformat()
    sig_id = str(uuid.uuid4())
    db.execute(
        """
        INSERT INTO spi_signals
            (signal_id, signal_client_id, submission_id, producer_id,
             ingress_mode, symbol, direction, confidence, horizon_hours,
             submitted_at, attribution_window_start, attribution_window_end,
             status, created_at, updated_at)
        VALUES (?,?,?,?,'native','BTC','bullish',0.7,1,?,?,?,?,?,?)
        """,
        (
            sig_id,
            sig_id,
            sig_id,
            producer_id,
            now,
            now,
            now,
            status,
            now,
            now,
        ),
    )


# ---------------------------------------------------------------------------
# 1. Valid transitions
# ---------------------------------------------------------------------------


class TestValidTransitions:
    def test_onboarding_to_shadow(self):
        db = _setup_db()
        _register_producer(db, "p1", "onboarding")
        result = transition(db, "p1", "shadow")
        assert result["lifecycle_state"] == "shadow"

    def test_shadow_to_active(self):
        db = _setup_db()
        _register_producer(db, "p1", "shadow")
        result = transition(db, "p1", "active")
        assert result["lifecycle_state"] == "active"

    def test_active_to_suspended(self):
        db = _setup_db()
        _register_producer(db, "p1", "active")
        result = transition(db, "p1", "suspended")
        assert result["lifecycle_state"] == "suspended"

    def test_suspended_to_active(self):
        db = _setup_db()
        _register_producer(db, "p1", "suspended")
        result = transition(db, "p1", "active")
        assert result["lifecycle_state"] == "active"

    def test_active_to_retired(self):
        db = _setup_db()
        _register_producer(db, "p1", "active")
        result = transition(db, "p1", "retired")
        assert result["lifecycle_state"] == "retired"


# ---------------------------------------------------------------------------
# 2. Invalid transitions raise ValueError
# ---------------------------------------------------------------------------


class TestInvalidTransitions:
    def test_onboarding_to_active_skips_shadow(self):
        db = _setup_db()
        _register_producer(db, "p1", "onboarding")
        with pytest.raises(ValueError, match="onboarding"):
            transition(db, "p1", "active")

    def test_onboarding_to_retired_invalid(self):
        db = _setup_db()
        _register_producer(db, "p1", "onboarding")
        with pytest.raises(ValueError):
            transition(db, "p1", "retired")

    def test_retired_has_no_valid_transitions(self):
        db = _setup_db()
        _register_producer(db, "p1", "retired")
        assert VALID_TRANSITIONS["retired"] == set()
        with pytest.raises(ValueError, match="retired"):
            transition(db, "p1", "active")

    def test_unknown_producer_raises(self):
        db = _setup_db()
        with pytest.raises(ValueError, match="not found"):
            transition(db, "no-such-producer", "active")


# ---------------------------------------------------------------------------
# 3. check_promotion_criteria
# ---------------------------------------------------------------------------


class TestCheckPromotionCriteria:
    def test_onboarding_to_shadow_below_threshold(self):
        db = _setup_db()
        _register_producer(db, "p1", "onboarding")
        # Insert only 3 signals
        for _ in range(3):
            _insert_signal(db, "p1")
        result = check_promotion_criteria(db, "p1")
        assert result["eligible"] is False
        assert result["current_state"] == "onboarding"
        assert result["target_state"] == "shadow"
        assert "3/5" in result["reason"]

    def test_onboarding_to_shadow_at_threshold(self):
        db = _setup_db()
        _register_producer(db, "p1", "onboarding")
        for _ in range(5):
            _insert_signal(db, "p1")
        result = check_promotion_criteria(db, "p1")
        assert result["eligible"] is True
        assert result["target_state"] == "shadow"

    def test_shadow_to_active_below_threshold(self):
        db = _setup_db()
        _register_producer(db, "p1", "shadow")
        # Only 8 resolved signals, karma fine
        for _ in range(8):
            _insert_signal(db, "p1", status="resolved")
        _insert_karma(db, "p1", epoch=1, running_karma=0.65)
        result = check_promotion_criteria(db, "p1")
        assert result["eligible"] is False
        assert "8/10" in result["reason"]

    def test_shadow_to_active_low_karma(self):
        db = _setup_db()
        _register_producer(db, "p1", "shadow")
        for _ in range(12):
            _insert_signal(db, "p1", status="resolved")
        _insert_karma(db, "p1", epoch=1, running_karma=0.45)
        result = check_promotion_criteria(db, "p1")
        assert result["eligible"] is False
        assert "0.45" in result["reason"] or "karma" in result["reason"].lower()

    def test_shadow_to_active_meets_criteria(self):
        db = _setup_db()
        _register_producer(db, "p1", "shadow")
        for _ in range(10):
            _insert_signal(db, "p1", status="resolved")
        _insert_karma(db, "p1", epoch=1, running_karma=0.60)
        result = check_promotion_criteria(db, "p1")
        assert result["eligible"] is True
        assert result["target_state"] == "active"


# ---------------------------------------------------------------------------
# 4. maybe_auto_promote
# ---------------------------------------------------------------------------


class TestMaybeAutoPromote:
    def test_promotes_when_eligible(self):
        db = _setup_db()
        _register_producer(db, "p1", "onboarding")
        for _ in range(5):
            _insert_signal(db, "p1")
        result = maybe_auto_promote(db, "p1")
        assert result is not None
        assert result["lifecycle_state"] == "shadow"

    def test_no_op_when_not_eligible(self):
        db = _setup_db()
        _register_producer(db, "p1", "onboarding")
        # Only 2 signals — not enough
        for _ in range(2):
            _insert_signal(db, "p1")
        result = maybe_auto_promote(db, "p1")
        assert result is None
        # State should still be onboarding
        p = get_producer(db, "p1")
        assert p["lifecycle_state"] == "onboarding"


# ---------------------------------------------------------------------------
# 5. Slash conditions
# ---------------------------------------------------------------------------


class TestKarmaFloorSlash:
    def test_triggers_at_below_030_for_3_epochs(self):
        db = _setup_db()
        _register_producer(db, "p1", "active")
        for epoch in range(3):
            _insert_karma(db, "p1", epoch=epoch, running_karma=0.25)
        result = _check_karma_floor(db, "p1")
        assert result is not None
        assert result["condition"] == "karma_floor"
        assert result["severity"] == "suspend"

    def test_no_trigger_when_karma_above_floor(self):
        db = _setup_db()
        _register_producer(db, "p1", "active")
        for epoch in range(3):
            _insert_karma(db, "p1", epoch=epoch, running_karma=0.45)
        result = _check_karma_floor(db, "p1")
        assert result is None

    def test_no_trigger_fewer_than_3_epochs(self):
        db = _setup_db()
        _register_producer(db, "p1", "active")
        _insert_karma(db, "p1", epoch=0, running_karma=0.20)
        result = _check_karma_floor(db, "p1")
        assert result is None


class TestSignalSpamSlash:
    def test_triggers_over_100_signals_per_hour(self):
        db = _setup_db()
        _register_producer(db, "p1", "active")
        # Insert 101 signals all within the last hour
        for _ in range(101):
            _insert_signal(db, "p1")
        result = _check_signal_spam(db, "p1")
        assert result is not None
        assert result["condition"] == "signal_spam"
        assert result["severity"] == "warn"

    def test_no_trigger_at_100_signals(self):
        db = _setup_db()
        _register_producer(db, "p1", "active")
        for _ in range(100):
            _insert_signal(db, "p1")
        result = _check_signal_spam(db, "p1")
        assert result is None

    def test_no_trigger_old_signals_outside_window(self):
        db = _setup_db()
        _register_producer(db, "p1", "active")
        # 200 signals but all from 2 hours ago
        old_time = (datetime.now(tz=UTC) - timedelta(hours=2)).isoformat()
        for _ in range(200):
            _insert_signal(db, "p1", submitted_at=old_time)
        result = _check_signal_spam(db, "p1")
        assert result is None


# ---------------------------------------------------------------------------
# 6. apply_slash
# ---------------------------------------------------------------------------


class TestApplySlash:
    def test_warn_logs_only_no_state_change(self):
        db = _setup_db()
        _register_producer(db, "p1", "active")
        result = apply_slash(db, "p1", "signal_spam", "warn")
        assert result["state_changed"] is False
        assert result["action"] == "logged"
        # State should still be active
        p = get_producer(db, "p1")
        assert p["lifecycle_state"] == "active"

    def test_suspend_transitions_to_suspended(self):
        db = _setup_db()
        _register_producer(db, "p1", "active")
        result = apply_slash(db, "p1", "karma_floor", "suspend")
        assert result["state_changed"] is True
        assert result["action"] == "suspended"
        p = get_producer(db, "p1")
        assert p["lifecycle_state"] == "suspended"


# ---------------------------------------------------------------------------
# 7. Full flow: register → accept 5 signals → auto-promote to shadow
# ---------------------------------------------------------------------------


class TestFullFlow:
    def test_register_accept_5_signals_auto_promote_to_shadow(self):
        db = _setup_db()

        # Register producer in onboarding
        _register_producer(db, "full-flow-producer", "onboarding")

        # Verify initial state
        p = get_producer(db, "full-flow-producer")
        assert p["lifecycle_state"] == "onboarding"

        # Accept 5 signals (last one should trigger auto-promotion)
        for i in range(5):
            accept_signal(
                producer_id="full-flow-producer",
                signal_client_id=f"client-{i}",
                submission_id=f"sub-{i}",
                symbol="BTC",
                direction="bullish",
                confidence=0.7,
                horizon_hours=1,
                ingress_mode="native",
                db=db,
            )

        # Producer should now be in shadow state
        p = get_producer(db, "full-flow-producer")
        assert p["lifecycle_state"] == "shadow", f"Expected shadow after 5 signals, got: {p['lifecycle_state']}"
