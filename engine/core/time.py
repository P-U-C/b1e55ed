"""engine.core.time

Perfect timing is a fiction. Optimal timing has texture.

This module is the *only* time helper surface in the codebase.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return an aware UTC datetime."""

    return datetime.now(tz=UTC)


def parse_dt(value: str) -> datetime:
    """Parse an ISO-8601 datetime string into an aware UTC datetime.

    Accepts:
    - `Z` suffix
    - explicit offsets
    - naive timestamps (assumed UTC)

    Raises:
        ValueError: if parsing fails.
    """

    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"

    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def staleness_ms(observed_at: datetime, *, now: datetime | None = None) -> int:
    """Return staleness in milliseconds.

    Args:
        observed_at: When the underlying data was observed.
        now: Override clock for testing.
    """

    ref = now or utc_now()
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    return int((ref - observed_at.astimezone(UTC)).total_seconds() * 1000)
