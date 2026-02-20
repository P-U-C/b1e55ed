"""engine.core.rate_limiter

Anti-spam controls for signal submission (S2).

Three layers:
1. Rate limit: max signals per contributor per time window
2. Diversity gate: can't spam same asset+direction repeatedly
3. Quota: daily submission cap per contributor

All checks are DB-backed (no in-memory state to lose on restart).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from engine.core.database import Database

# Defaults — configurable per deployment
DEFAULT_MAX_PER_HOUR = 20
DEFAULT_MAX_PER_DAY = 100
DEFAULT_DUPLICATE_WINDOW_MINUTES = 30  # same asset+direction cooldown
DEFAULT_MIN_DIVERSITY_ASSETS = 1  # min unique assets per day (0 = disabled)


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    reason: str = ""
    retry_after_seconds: int = 0


class SignalRateLimiter:
    """Rate limiting and anti-spam for signal submissions."""

    def __init__(
        self,
        db: Database,
        *,
        max_per_hour: int = DEFAULT_MAX_PER_HOUR,
        max_per_day: int = DEFAULT_MAX_PER_DAY,
        duplicate_window_minutes: int = DEFAULT_DUPLICATE_WINDOW_MINUTES,
    ):
        self._db = db
        self.max_per_hour = max_per_hour
        self.max_per_day = max_per_day
        self.duplicate_window_minutes = duplicate_window_minutes

    def check(
        self,
        *,
        contributor_id: str,
        asset: str | None = None,
        direction: str | None = None,
    ) -> RateLimitResult:
        """Check if a signal submission is allowed. Call before inserting."""
        now = datetime.now(tz=UTC)

        # 1. Hourly rate limit
        hour_ago = (now - timedelta(hours=1)).isoformat()
        hour_count = self._count_since(contributor_id, hour_ago)
        if hour_count >= self.max_per_hour:
            return RateLimitResult(
                allowed=False,
                reason=f"Rate limit: {self.max_per_hour} signals/hour exceeded",
                retry_after_seconds=3600,
            )

        # 2. Daily quota
        day_ago = (now - timedelta(days=1)).isoformat()
        day_count = self._count_since(contributor_id, day_ago)
        if day_count >= self.max_per_day:
            return RateLimitResult(
                allowed=False,
                reason=f"Daily quota: {self.max_per_day} signals/day exceeded",
                retry_after_seconds=86400,
            )

        # 3. Duplicate signal detection (same asset + direction within window)
        if asset and direction and self.duplicate_window_minutes > 0:
            window_start = (now - timedelta(minutes=self.duplicate_window_minutes)).isoformat()
            dup_count = self._count_duplicates(contributor_id, asset, direction, window_start)
            if dup_count > 0:
                return RateLimitResult(
                    allowed=False,
                    reason=f"Duplicate: same asset+direction within {self.duplicate_window_minutes}min window",
                    retry_after_seconds=self.duplicate_window_minutes * 60,
                )

        return RateLimitResult(allowed=True)

    def _count_since(self, contributor_id: str, since_iso: str) -> int:
        row = self._db.conn.execute(
            "SELECT COUNT(1) FROM contributor_signals WHERE contributor_id = ? AND created_at >= ?",
            (contributor_id, since_iso),
        ).fetchone()
        return int(row[0]) if row else 0

    def _count_duplicates(self, contributor_id: str, asset: str, direction: str, since_iso: str) -> int:
        row = self._db.conn.execute(
            """
            SELECT COUNT(1) FROM contributor_signals
            WHERE contributor_id = ? AND signal_asset = ? AND signal_direction = ? AND created_at >= ?
            """,
            (contributor_id, asset, direction, since_iso),
        ).fetchone()
        return int(row[0]) if row else 0

    def get_usage(self, contributor_id: str) -> dict:
        """Return current usage stats for a contributor."""
        now = datetime.now(tz=UTC)
        hour_ago = (now - timedelta(hours=1)).isoformat()
        day_ago = (now - timedelta(days=1)).isoformat()

        return {
            "hourly_used": self._count_since(contributor_id, hour_ago),
            "hourly_limit": self.max_per_hour,
            "daily_used": self._count_since(contributor_id, day_ago),
            "daily_limit": self.max_per_day,
        }
