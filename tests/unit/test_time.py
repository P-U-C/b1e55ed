from __future__ import annotations

from datetime import UTC, datetime, timedelta

from engine.core.time import parse_dt, staleness_ms, utc_now


def test_utc_now_is_aware_and_utc() -> None:
    now = utc_now()
    assert now.tzinfo is not None
    assert now.tzinfo == UTC


def test_parse_dt_accepts_z_suffix() -> None:
    dt = parse_dt("2026-02-17T23:33:00Z")
    assert dt.tzinfo == UTC
    assert dt.year == 2026


def test_parse_dt_assumes_naive_is_utc() -> None:
    dt = parse_dt("2026-02-17T23:33:00")
    assert dt.tzinfo == UTC


def test_staleness_ms_is_non_negative() -> None:
    base = datetime(2026, 2, 17, 23, 33, tzinfo=UTC)
    now = base + timedelta(seconds=1)
    assert staleness_ms(base, now=now) == 1000
