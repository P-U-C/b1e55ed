"""Tests for P2.1 -- Brier score tracking and forecast calibration."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from engine.brain.calibration import (
    brier_summary,
    get_pending_resolution,
    register_forecast,
    resolve_forecast,
)
from engine.core.database import Database

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    UTC = UTC  # noqa: N806


def _mkdb(tmp_path: Path) -> Database:
    return Database(tmp_path / "brain.db")


def _minutes_ago(minutes: int) -> str:
    return (datetime.now(tz=UTC) - timedelta(minutes=minutes)).isoformat()


def _register(
    db: Database,
    *,
    forecast_id: str,
    producer_name: str = "unit-producer",
    asset: str = "BTC",
    regime: str = "unknown",
    horizon: str = "1h",
    direction: str = "bullish",
    confidence: float = 0.8,
    emitted_at: str | None = None,
    price_at_emit: float | None = None,
) -> None:
    register_forecast(
        db=db,
        forecast_id=forecast_id,
        producer_name=producer_name,
        asset=asset,
        regime=regime,
        horizon=horizon,
        direction=direction,
        confidence=confidence,
        emitted_at=emitted_at or _minutes_ago(120),
        price_at_emit=price_at_emit,
    )


# ---------- Schema ----------


def test_forecast_calibration_table_exists_after_db_init(temp_dir: Path) -> None:
    db = _mkdb(temp_dir)
    try:
        row = db.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='forecast_calibration'").fetchone()
        assert row is not None
    finally:
        db.close()


# ---------- register_forecast ----------


def test_register_forecast_inserts_correct_fields(temp_dir: Path) -> None:
    db = _mkdb(temp_dir)
    try:
        emitted_at = datetime(2026, 2, 1, tzinfo=UTC).isoformat()
        register_forecast(
            db=db,
            forecast_id="fc-1",
            producer_name="p1",
            asset="BTC",
            regime="risk-on",
            horizon="4h",
            direction="bullish",
            confidence=0.72,
            emitted_at=emitted_at,
            price_at_emit=101_000.0,
        )

        row = db.conn.execute(
            """SELECT forecast_id, producer_name, asset, regime, horizon, direction,
                      confidence, emitted_at, price_at_emit, calibrated, outcome, brier_score
               FROM forecast_calibration WHERE forecast_id = 'fc-1'"""
        ).fetchone()

        assert row is not None
        assert row[0] == "fc-1"
        assert row[1] == "p1"
        assert row[2] == "BTC"
        assert row[3] == "risk-on"
        assert row[4] == "4h"
        assert row[5] == "bullish"
        assert row[6] == pytest.approx(0.72)
        assert row[7] == emitted_at
        assert row[8] == pytest.approx(101_000.0)
        assert row[9] == 0  # calibrated default
        assert row[10] is None  # outcome
        assert row[11] is None  # brier_score
    finally:
        db.close()


def test_register_forecast_is_idempotent(temp_dir: Path) -> None:
    db = _mkdb(temp_dir)
    try:
        ts = _minutes_ago(90)
        _register(db, forecast_id="fc-dup", confidence=0.9, emitted_at=ts)
        # Second call with different confidence -- INSERT OR IGNORE keeps first
        _register(db, forecast_id="fc-dup", confidence=0.2, emitted_at=ts)

        count = db.conn.execute("SELECT COUNT(*) FROM forecast_calibration WHERE forecast_id = 'fc-dup'").fetchone()[0]
        conf = db.conn.execute("SELECT confidence FROM forecast_calibration WHERE forecast_id = 'fc-dup'").fetchone()[0]

        assert count == 1
        assert conf == pytest.approx(0.9)
    finally:
        db.close()


# ---------- resolve_forecast ----------


def test_resolve_forecast_sets_outcome_brier_and_resolved_at(temp_dir: Path) -> None:
    db = _mkdb(temp_dir)
    try:
        _register(db, forecast_id="fc-res", confidence=0.8)
        resolve_forecast(db=db, forecast_id="fc-res", outcome=1.0, price_at_resolve=102_500.0)

        row = db.conn.execute("SELECT outcome, brier_score, price_at_resolve, resolved_at FROM forecast_calibration WHERE forecast_id = 'fc-res'").fetchone()

        assert row[0] == pytest.approx(1.0)
        assert row[1] == pytest.approx(0.04)  # (0.8 - 1.0)^2
        assert row[2] == pytest.approx(102_500.0)
        assert row[3] is not None  # resolved_at timestamp
    finally:
        db.close()


@pytest.mark.parametrize(
    ("confidence", "outcome", "expected_brier"),
    [
        (0.8, 1.0, 0.04),
        (0.5, 0.0, 0.25),
        (1.0, 1.0, 0.0),
        (0.0, 0.0, 0.0),
        (0.7, 0.0, 0.49),
    ],
)
def test_brier_score_formula_spot_checks(
    temp_dir: Path,
    confidence: float,
    outcome: float,
    expected_brier: float,
) -> None:
    db = _mkdb(temp_dir)
    try:
        fid = f"fc-brier-{confidence}-{outcome}"
        _register(db, forecast_id=fid, confidence=confidence)
        resolve_forecast(db=db, forecast_id=fid, outcome=outcome)

        brier = db.conn.execute("SELECT brier_score FROM forecast_calibration WHERE forecast_id = ?", (fid,)).fetchone()[0]
        assert brier == pytest.approx(expected_brier)
    finally:
        db.close()


def test_resolve_forecast_unknown_id_logs_warning_does_not_crash(temp_dir: Path, caplog: pytest.LogCaptureFixture) -> None:
    db = _mkdb(temp_dir)
    try:
        with caplog.at_level(logging.WARNING, logger="engine.brain.calibration"):
            resolve_forecast(db=db, forecast_id="nonexistent-id", outcome=1.0)

        assert any("unknown forecast_id nonexistent-id" in r.message for r in caplog.records)
    finally:
        db.close()


# ---------- get_pending_resolution ----------


def test_get_pending_resolution_returns_only_elapsed_unresolved(temp_dir: Path) -> None:
    db = _mkdb(temp_dir)
    try:
        # 15m horizon, emitted 25 min ago -> elapsed
        _register(db, forecast_id="fc-elapsed", horizon="15m", emitted_at=_minutes_ago(25))
        # 15m horizon, emitted 5 min ago -> NOT elapsed
        _register(db, forecast_id="fc-fresh", horizon="15m", emitted_at=_minutes_ago(5))
        # 15m horizon, emitted 30 min ago but already resolved
        _register(db, forecast_id="fc-done", horizon="15m", emitted_at=_minutes_ago(30))
        resolve_forecast(db=db, forecast_id="fc-done", outcome=1.0)

        pending = get_pending_resolution(db=db, max_age_minutes=120)
        ids = {p.forecast_id for p in pending}

        assert "fc-elapsed" in ids
        assert "fc-fresh" not in ids
        assert "fc-done" not in ids
    finally:
        db.close()


def test_get_pending_resolution_excludes_not_yet_elapsed(temp_dir: Path) -> None:
    db = _mkdb(temp_dir)
    try:
        # 1h horizon, only 20 min old -> not elapsed
        _register(db, forecast_id="fc-too-new", horizon="1h", emitted_at=_minutes_ago(20))

        pending = get_pending_resolution(db=db, max_age_minutes=300)
        assert pending == []
    finally:
        db.close()


# ---------- brier_summary ----------


def test_brier_summary_correct_mean_and_resolution_rate(temp_dir: Path) -> None:
    db = _mkdb(temp_dir)
    try:
        _register(db, forecast_id="s1", producer_name="ps", regime="BULL", confidence=0.8)
        _register(db, forecast_id="s2", producer_name="ps", regime="BULL", confidence=0.6)
        _register(db, forecast_id="s3", producer_name="ps", regime="BEAR", confidence=0.5)
        _register(db, forecast_id="s4", producer_name="ps", regime="BEAR", confidence=0.9)

        resolve_forecast(db=db, forecast_id="s1", outcome=1.0)  # brier = 0.04
        resolve_forecast(db=db, forecast_id="s2", outcome=0.0)  # brier = 0.36
        resolve_forecast(db=db, forecast_id="s3", outcome=0.0)  # brier = 0.25
        # s4 unresolved

        summary = brier_summary(db=db, producer_name="ps", window_days=30)

        assert summary["count"] == 3
        assert summary["resolution_rate"] == pytest.approx(0.75)
        assert summary["mean_brier"] == pytest.approx((0.04 + 0.36 + 0.25) / 3, abs=1e-4)
        assert "BULL" in summary["regime_breakdown"]
        assert summary["regime_breakdown"]["BULL"]["count"] == 2
        assert summary["regime_breakdown"]["BULL"]["mean_brier"] == pytest.approx(0.2)
        assert summary["regime_breakdown"]["BEAR"]["mean_brier"] == pytest.approx(0.25)
    finally:
        db.close()


def test_brier_summary_handles_empty_gracefully(temp_dir: Path) -> None:
    db = _mkdb(temp_dir)
    try:
        summary = brier_summary(db=db, producer_name="ghost", window_days=30)

        assert summary["count"] == 0
        assert summary["mean_brier"] == 0.0
        assert summary["mean_confidence"] == 0.0
        assert summary["resolution_rate"] == 0.0
        assert summary["regime_breakdown"] == {}
    finally:
        db.close()
