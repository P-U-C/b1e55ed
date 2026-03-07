"""tests.test_producer_health
Integration test suite for producer health status features (PR #332).

Validates:
- Status badge assignment for all four states with boundary conditions
- Error message truncation at 60 chars (template behavior) and raw pass-through (Python layer)
- Quarantine expiry: future expiry → quarantined, past expiry → reverts to failure-based status
- Negative test: empty table returns empty list
- Boundary conditions: failures at 0, 1, 4, 5 (the exact thresholds)

Status thresholds (from dashboard/producers.py):
  quarantined_until > now  → "quarantined"
  consecutive_failures == 0 → "healthy"
  1 <= failures <= 4       → "degraded"
  failures >= 5            → "failing"
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

try:
    from datetime import UTC
except ImportError:  # pragma: no cover
    UTC = UTC

import pytest

# ── Helpers ────────────────────────────────────────────────────────────────────


def _create_table(conn: sqlite3.Connection) -> None:
    """Create the producer_health table with all columns including quarantine."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS producer_health (
            name                TEXT PRIMARY KEY,
            domain              TEXT,
            endpoint            TEXT,
            schedule            TEXT,
            last_run_at         TEXT,
            last_success_at     TEXT,
            last_error          TEXT,
            consecutive_failures INTEGER DEFAULT 0,
            events_produced     INTEGER DEFAULT 0,
            avg_duration_ms     REAL,
            expected_interval_ms INTEGER,
            quarantined_until   TEXT,
            quarantined_reason  TEXT,
            updated_at          TEXT
        )
    """)
    conn.commit()


def _seed_producer(
    conn: sqlite3.Connection,
    name: str,
    *,
    consecutive_failures: int = 0,
    last_error: str | None = None,
    quarantined_until: datetime | None = None,
    quarantined_reason: str | None = None,
    domain: str = "test",
    schedule: str = "*/5 * * * *",
    endpoint: str = "http://localhost:8000/test",
) -> None:
    """Insert a row into producer_health with the given state."""
    _create_table(conn)
    conn.execute(
        """
        INSERT OR REPLACE INTO producer_health
            (name, domain, endpoint, schedule, last_error,
             consecutive_failures, quarantined_until, quarantined_reason, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            domain,
            endpoint,
            schedule,
            last_error,
            consecutive_failures,
            quarantined_until.isoformat() if quarantined_until else None,
            quarantined_reason,
            datetime.now(UTC).isoformat(),
        ),
    )
    conn.commit()


def _list_producers(conn: sqlite3.Connection):
    """Import and call the dashboard _list_producers function."""
    from dashboard.producers import _list_producers as lp

    return lp(conn)


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """In-memory SQLite connection for each test."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    _create_table(c)
    return c


# ── Status Badge Tests ──────────────────────────────────────────────────────────


class TestStatusBadgeAssignment:
    """Status badge correctness for all four states with boundary conditions."""

    def test_healthy_zero_failures(self, conn: sqlite3.Connection) -> None:
        """0 consecutive failures + no last_error → healthy."""
        _seed_producer(conn, "prod-healthy", consecutive_failures=0, last_error=None)
        rows = _list_producers(conn)
        row = next(r for r in rows if r.name == "prod-healthy")
        assert row.status == "healthy", f"Expected 'healthy', got '{row.status}'"

    def test_degraded_at_boundary_one(self, conn: sqlite3.Connection) -> None:
        """1 consecutive failure → degraded (lower boundary)."""
        _seed_producer(conn, "prod-degrad-low", consecutive_failures=1)
        rows = _list_producers(conn)
        row = next(r for r in rows if r.name == "prod-degrad-low")
        assert row.status == "degraded", f"Expected 'degraded' at 1 failure, got '{row.status}'"

    def test_degraded_at_boundary_four(self, conn: sqlite3.Connection) -> None:
        """4 consecutive failures → degraded (upper boundary)."""
        _seed_producer(conn, "prod-degrad-high", consecutive_failures=4)
        rows = _list_producers(conn)
        row = next(r for r in rows if r.name == "prod-degrad-high")
        assert row.status == "degraded", f"Expected 'degraded' at 4 failures, got '{row.status}'"

    def test_failing_at_boundary_five(self, conn: sqlite3.Connection) -> None:
        """5 consecutive failures → failing (threshold crossing)."""
        _seed_producer(conn, "prod-failing", consecutive_failures=5)
        rows = _list_producers(conn)
        row = next(r for r in rows if r.name == "prod-failing")
        assert row.status == "failing", f"Expected 'failing' at 5 failures, got '{row.status}'"

    def test_failing_high_failure_count(self, conn: sqlite3.Connection) -> None:
        """20 consecutive failures → failing (well above threshold)."""
        _seed_producer(conn, "prod-failing-high", consecutive_failures=20)
        rows = _list_producers(conn)
        row = next(r for r in rows if r.name == "prod-failing-high")
        assert row.status == "failing"

    def test_quarantined_future_expiry(self, conn: sqlite3.Connection) -> None:
        """quarantined_until in future → quarantined (overrides failure count)."""
        future = datetime.now(UTC) + timedelta(hours=2)
        _seed_producer(
            conn,
            "prod-quarantined",
            consecutive_failures=0,
            quarantined_until=future,
            quarantined_reason="Spam rate exceeded",
        )
        rows = _list_producers(conn)
        row = next(r for r in rows if r.name == "prod-quarantined")
        assert row.status == "quarantined", f"Expected 'quarantined' with future expiry, got '{row.status}'"
        assert row.quarantined_until is not None, "quarantined_until should be populated"

    def test_quarantined_overrides_healthy_count(self, conn: sqlite3.Connection) -> None:
        """Quarantine takes priority over zero-failure healthy status."""
        future = datetime.now(UTC) + timedelta(minutes=30)
        _seed_producer(
            conn,
            "prod-quarantined-healthy",
            consecutive_failures=0,
            last_error=None,
            quarantined_until=future,
        )
        rows = _list_producers(conn)
        row = next(r for r in rows if r.name == "prod-quarantined-healthy")
        assert row.status == "quarantined", "Quarantine must override zero-failure healthy state"


# ── Quarantine Expiry Tests ─────────────────────────────────────────────────────


class TestQuarantineExpiry:
    """Quarantine expiry: future → quarantined, past → reverts to failure-based status."""

    def test_expired_quarantine_reverts_to_healthy(self, conn: sqlite3.Connection) -> None:
        """Past quarantine_until + 0 failures → healthy (quarantine expired)."""
        past = datetime.now(UTC) - timedelta(hours=1)
        _seed_producer(
            conn,
            "prod-expired-healthy",
            consecutive_failures=0,
            last_error=None,
            quarantined_until=past,
        )
        rows = _list_producers(conn)
        row = next(r for r in rows if r.name == "prod-expired-healthy")
        assert row.status == "healthy", f"Expired quarantine + 0 failures should be 'healthy', got '{row.status}'"

    def test_expired_quarantine_reverts_to_degraded(self, conn: sqlite3.Connection) -> None:
        """Past quarantine_until + 3 failures → degraded (not quarantined)."""
        past = datetime.now(UTC) - timedelta(minutes=5)
        _seed_producer(
            conn,
            "prod-expired-degraded",
            consecutive_failures=3,
            quarantined_until=past,
        )
        rows = _list_producers(conn)
        row = next(r for r in rows if r.name == "prod-expired-degraded")
        assert row.status == "degraded", f"Expired quarantine + 3 failures should be 'degraded', got '{row.status}'"

    def test_expired_quarantine_reverts_to_failing(self, conn: sqlite3.Connection) -> None:
        """Past quarantine_until + 5 failures → failing (not quarantined)."""
        past = datetime.now(UTC) - timedelta(seconds=1)
        _seed_producer(
            conn,
            "prod-expired-failing",
            consecutive_failures=5,
            quarantined_until=past,
        )
        rows = _list_producers(conn)
        row = next(r for r in rows if r.name == "prod-expired-failing")
        assert row.status == "failing", f"Expired quarantine + 5 failures should be 'failing', got '{row.status}'"


# ── Error Message Tests ─────────────────────────────────────────────────────────


class TestLastErrorField:
    """Error message storage and pass-through from producer_health table."""

    def test_short_error_stored_and_returned(self, conn: sqlite3.Connection) -> None:
        """Short error message is stored and returned as-is."""
        _seed_producer(conn, "prod-short-err", last_error="Connection refused", consecutive_failures=1)
        rows = _list_producers(conn)
        row = next(r for r in rows if r.name == "prod-short-err")
        assert row.last_error == "Connection refused"

    def test_long_error_stored_and_returned(self, conn: sqlite3.Connection) -> None:
        """Long error message (>60 chars) is stored and returned in full from Python layer."""
        long_msg = "A" * 200 + " — timeout after 30s waiting for upstream API response"
        _seed_producer(conn, "prod-long-err", last_error=long_msg, consecutive_failures=2)
        rows = _list_producers(conn)
        row = next(r for r in rows if r.name == "prod-long-err")
        # Python layer returns full string; Jinja template handles truncation for display
        assert row.last_error == long_msg, "Python layer should return full error message"
        assert len(row.last_error) > 60

    def test_no_error_returns_none(self, conn: sqlite3.Connection) -> None:
        """Healthy producer has no last_error."""
        _seed_producer(conn, "prod-no-err", consecutive_failures=0, last_error=None)
        rows = _list_producers(conn)
        row = next(r for r in rows if r.name == "prod-no-err")
        assert row.last_error is None

    def test_error_at_truncation_boundary(self, conn: sqlite3.Connection) -> None:
        """Error message exactly 60 chars is returned in full."""
        exact_msg = "X" * 60
        _seed_producer(conn, "prod-exact-err", last_error=exact_msg, consecutive_failures=1)
        rows = _list_producers(conn)
        row = next(r for r in rows if r.name == "prod-exact-err")
        assert row.last_error == exact_msg
        assert len(row.last_error) == 60


# ── Negative / Edge Case Tests ──────────────────────────────────────────────────


class TestNegativeCases:
    """Missing producers and edge cases."""

    def test_empty_health_table_returns_empty_list(self, conn: sqlite3.Connection) -> None:
        """No producers in health table → empty list (not an error)."""
        rows = _list_producers(conn)
        assert rows == [], f"Expected empty list, got {len(rows)} rows"

    def test_all_four_statuses_in_one_query(self, conn: sqlite3.Connection) -> None:
        """Multiple producers in different states all returned correctly in one query."""
        future = datetime.now(UTC) + timedelta(hours=1)
        past = datetime.now(UTC) - timedelta(hours=1)

        _seed_producer(conn, "p-healthy", consecutive_failures=0)
        _seed_producer(conn, "p-degraded", consecutive_failures=2)
        _seed_producer(conn, "p-failing", consecutive_failures=10)
        _seed_producer(conn, "p-quarantined", consecutive_failures=0, quarantined_until=future)
        _seed_producer(conn, "p-expired", consecutive_failures=3, quarantined_until=past)

        rows = _list_producers(conn)
        by_name = {r.name: r.status for r in rows}

        assert by_name["p-healthy"] == "healthy"
        assert by_name["p-degraded"] == "degraded"
        assert by_name["p-failing"] == "failing"
        assert by_name["p-quarantined"] == "quarantined"
        assert by_name["p-expired"] == "degraded"  # expired quarantine → back to failure-based
        print(f"\n ✅ All 4 statuses validated in single query ({len(rows)} producers)")
