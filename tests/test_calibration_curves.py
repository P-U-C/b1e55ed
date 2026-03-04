"""Tests for P2.2 — per-producer calibration curves."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from engine.brain.calibration_curves import (
    get_calibration_curve,
    is_well_calibrated,
    update_calibration_curves,
)
from engine.core.database import Database

_FORECAST_CALIBRATION_DDL = """
CREATE TABLE IF NOT EXISTS forecast_calibration (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    forecast_id TEXT NOT NULL UNIQUE,
    producer_name TEXT NOT NULL,
    asset TEXT NOT NULL,
    regime TEXT NOT NULL DEFAULT 'unknown',
    horizon TEXT NOT NULL,
    direction TEXT NOT NULL,
    confidence REAL NOT NULL,
    calibrated INTEGER NOT NULL DEFAULT 0,
    outcome REAL,
    brier_score REAL,
    price_at_emit REAL,
    price_at_resolve REAL,
    emitted_at TEXT NOT NULL,
    resolved_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _seed(
    db: Database,
    *,
    producer_name: str,
    confidence: float,
    outcome: float,
    asset: str = "ALL",
    regime: str = "unknown",
    resolved: bool = True,
    brier_score: float | None = None,
) -> None:
    if brier_score is None:
        brier_score = (confidence - outcome) ** 2
    now = datetime.now(tz=UTC).isoformat()
    db.conn.execute(
        """INSERT INTO forecast_calibration
            (forecast_id, producer_name, asset, regime, horizon, direction,
             confidence, calibrated, outcome, brier_score, emitted_at, resolved_at)
        VALUES (?, ?, ?, ?, '4h', 'bullish', ?, 0, ?, ?, ?, ?)""",
        (str(uuid4()), producer_name, asset, regime, confidence, outcome, brier_score, now, now if resolved else None),
    )
    db.conn.commit()


@pytest.fixture()
def cdb(temp_dir: Path) -> Database:
    db = Database(temp_dir / "brain.db")
    db.conn.executescript(_FORECAST_CALIBRATION_DDL)
    try:
        yield db
    finally:
        db.close()


# --- 11 tests ---


def test_update_no_data_returns_empty(cdb: Database) -> None:
    assert update_calibration_curves(cdb, "pa") == []


def test_update_07_bucket_correct_win_rate(cdb: Database) -> None:
    _seed(cdb, producer_name="pa", confidence=0.75, outcome=1.0)
    result = update_calibration_curves(cdb, "pa")
    assert len(result) == 1
    assert result[0]["bucket"] == "0.7-0.8"
    assert result[0]["sample_count"] == 1
    assert result[0]["observed_win_rate"] == 1.0


def test_win_rate_two_of_three(cdb: Database) -> None:
    _seed(cdb, producer_name="pa", confidence=0.72, outcome=1.0)
    _seed(cdb, producer_name="pa", confidence=0.74, outcome=1.0)
    _seed(cdb, producer_name="pa", confidence=0.76, outcome=0.0)
    result = update_calibration_curves(cdb, "pa")
    bucket = next(r for r in result if r["bucket"] == "0.7-0.8")
    assert bucket["observed_win_rate"] == 0.6667
    assert bucket["sample_count"] == 3


def test_mean_brier_is_average(cdb: Database) -> None:
    b1 = (0.71 - 1.0) ** 2
    b2 = (0.74 - 1.0) ** 2
    b3 = (0.77 - 0.0) ** 2
    _seed(cdb, producer_name="pa", confidence=0.71, outcome=1.0, brier_score=b1)
    _seed(cdb, producer_name="pa", confidence=0.74, outcome=1.0, brier_score=b2)
    _seed(cdb, producer_name="pa", confidence=0.77, outcome=0.0, brier_score=b3)
    result = update_calibration_curves(cdb, "pa")
    bucket = next(r for r in result if r["bucket"] == "0.7-0.8")
    assert bucket["mean_brier_score"] == round((b1 + b2 + b3) / 3, 4)


def test_get_curve_empty_when_no_rows(cdb: Database) -> None:
    assert get_calibration_curve(cdb, "pa") == []


def test_get_curve_returns_rows_after_update(cdb: Database) -> None:
    _seed(cdb, producer_name="pa", confidence=0.92, outcome=1.0)
    update_calibration_curves(cdb, "pa")
    curve = get_calibration_curve(cdb, "pa")
    assert len(curve) == 1
    assert curve[0]["bucket"] == "0.9+"
    assert curve[0]["last_updated"] is not None


def test_update_is_idempotent(cdb: Database) -> None:
    _seed(cdb, producer_name="pa", confidence=0.91, outcome=1.0)
    first = update_calibration_curves(cdb, "pa")
    second = update_calibration_curves(cdb, "pa")
    assert first == second
    count = cdb.conn.execute(
        "SELECT COUNT(*) FROM producer_calibration WHERE producer_name = ?",
        ("pa",),
    ).fetchone()[0]
    assert count == 1


def test_upsert_updates_existing_row(cdb: Database) -> None:
    _seed(cdb, producer_name="pa", confidence=0.73, outcome=1.0)
    update_calibration_curves(cdb, "pa")
    _seed(cdb, producer_name="pa", confidence=0.75, outcome=0.0)
    update_calibration_curves(cdb, "pa")
    curve = get_calibration_curve(cdb, "pa")
    bucket = next(r for r in curve if r["bucket"] == "0.7-0.8")
    assert bucket["sample_count"] == 2
    assert bucket["observed_win_rate"] == 0.5


def test_is_well_calibrated_false_below_threshold(cdb: Database) -> None:
    _seed(cdb, producer_name="pa", confidence=0.92, outcome=1.0)
    update_calibration_curves(cdb, "pa")
    assert is_well_calibrated(cdb, "pa", min_samples=2) is False


def test_is_well_calibrated_true_above_threshold(cdb: Database) -> None:
    _seed(cdb, producer_name="pa", confidence=0.92, outcome=1.0)
    _seed(cdb, producer_name="pa", confidence=0.95, outcome=0.0)
    update_calibration_curves(cdb, "pa")
    assert is_well_calibrated(cdb, "pa", min_samples=2) is True


def test_asset_regime_filtering_isolated(cdb: Database) -> None:
    _seed(cdb, producer_name="pa", confidence=0.74, outcome=1.0, asset="BTC", regime="bull")
    update_calibration_curves(cdb, "pa", asset="BTC", regime="bull")
    btc = get_calibration_curve(cdb, "pa", asset="BTC", regime="bull")
    default = get_calibration_curve(cdb, "pa", asset="ALL", regime="unknown")
    assert len(btc) == 1
    assert default == []


def test_update_handles_null_outcome_without_crashing(cdb: Database) -> None:
    """Regression: float(outcome) raises TypeError if outcome IS NULL.
    A row with resolved_at set but outcome NULL must be skipped (counted as neither hit nor miss).
    """
    from datetime import UTC, datetime
    from uuid import uuid4

    now = datetime.now(tz=UTC).isoformat()
    # Insert a row with resolved_at set but outcome NULL
    cdb.conn.execute(
        """INSERT INTO forecast_calibration
            (forecast_id, producer_name, asset, regime, horizon, direction,
             confidence, calibrated, outcome, brier_score, emitted_at, resolved_at)
        VALUES (?, 'pa', 'ALL', 'unknown', '4h', 'bullish', 0.75, 0, NULL, NULL, ?, ?)""",
        (str(uuid4()), now, now),
    )
    cdb.conn.commit()
    # Should not raise TypeError
    result = update_calibration_curves(cdb, "pa")
    # Row with NULL outcome counts in sample_count=1 but win_rate=0 (not a hit)
    assert isinstance(result, list)
