"""Signal rate limiting and anti-spam (S2)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from engine.core.contributors import ContributorRegistry
from engine.core.database import Database
from engine.core.rate_limiter import SignalRateLimiter


def _insert_signal(
    db: Database, *, contributor_id: str, event_id: str, asset: str = "BTC", direction: str = "bullish", created_at: datetime | None = None
) -> None:
    ts = (created_at or datetime.now(tz=UTC)).isoformat()
    with db.conn:
        db.conn.execute(
            "INSERT INTO contributor_signals (contributor_id, event_id, signal_asset, signal_direction, created_at) VALUES (?, ?, ?, ?, ?)",
            (contributor_id, event_id, asset, direction, ts),
        )


def test_allows_under_limit(tmp_path: Path) -> None:
    db = Database(tmp_path / "db.sqlite")
    reg = ContributorRegistry(db)
    c = reg.register(node_id="n1", name="alice", role="agent", metadata={})

    limiter = SignalRateLimiter(db, max_per_hour=5, max_per_day=10)
    result = limiter.check(contributor_id=c.id)
    assert result.allowed


def test_blocks_hourly_excess(tmp_path: Path) -> None:
    db = Database(tmp_path / "db.sqlite")
    reg = ContributorRegistry(db)
    c = reg.register(node_id="n1", name="alice", role="agent", metadata={})

    limiter = SignalRateLimiter(db, max_per_hour=3, max_per_day=100)

    for i in range(3):
        _insert_signal(db, contributor_id=c.id, event_id=f"e{i}", asset=f"ASSET{i}", direction="bullish")

    result = limiter.check(contributor_id=c.id)
    assert not result.allowed
    assert "signals/hour" in result.reason


def test_blocks_daily_excess(tmp_path: Path) -> None:
    db = Database(tmp_path / "db.sqlite")
    reg = ContributorRegistry(db)
    c = reg.register(node_id="n1", name="alice", role="agent", metadata={})

    limiter = SignalRateLimiter(db, max_per_hour=100, max_per_day=5)

    for i in range(5):
        _insert_signal(db, contributor_id=c.id, event_id=f"e{i}", asset=f"ASSET{i}")

    result = limiter.check(contributor_id=c.id)
    assert not result.allowed
    assert "signals/day" in result.reason


def test_blocks_duplicate_asset_direction(tmp_path: Path) -> None:
    db = Database(tmp_path / "db.sqlite")
    reg = ContributorRegistry(db)
    c = reg.register(node_id="n1", name="alice", role="agent", metadata={})

    limiter = SignalRateLimiter(db, duplicate_window_minutes=30)
    _insert_signal(db, contributor_id=c.id, event_id="e1", asset="BTC", direction="bullish")

    # Same asset+direction within window = blocked
    result = limiter.check(contributor_id=c.id, asset="BTC", direction="bullish")
    assert not result.allowed
    assert "Duplicate" in result.reason

    # Different asset = allowed
    result2 = limiter.check(contributor_id=c.id, asset="ETH", direction="bullish")
    assert result2.allowed

    # Same asset, different direction = allowed
    result3 = limiter.check(contributor_id=c.id, asset="BTC", direction="bearish")
    assert result3.allowed


def test_old_signals_dont_count(tmp_path: Path) -> None:
    db = Database(tmp_path / "db.sqlite")
    reg = ContributorRegistry(db)
    c = reg.register(node_id="n1", name="alice", role="agent", metadata={})

    limiter = SignalRateLimiter(db, max_per_hour=2, max_per_day=100)

    # Insert signals from 2 hours ago
    old = datetime.now(tz=UTC) - timedelta(hours=2)
    for i in range(5):
        _insert_signal(db, contributor_id=c.id, event_id=f"old{i}", asset=f"A{i}", created_at=old)

    # Should be allowed — old signals outside hourly window
    result = limiter.check(contributor_id=c.id)
    assert result.allowed


def test_usage_stats(tmp_path: Path) -> None:
    db = Database(tmp_path / "db.sqlite")
    reg = ContributorRegistry(db)
    c = reg.register(node_id="n1", name="alice", role="agent", metadata={})

    limiter = SignalRateLimiter(db, max_per_hour=10, max_per_day=50)
    _insert_signal(db, contributor_id=c.id, event_id="e1", asset="BTC")
    _insert_signal(db, contributor_id=c.id, event_id="e2", asset="ETH")

    usage = limiter.get_usage(c.id)
    assert usage["hourly_used"] == 2
    assert usage["hourly_limit"] == 10
    assert usage["daily_used"] == 2
    assert usage["daily_limit"] == 50
