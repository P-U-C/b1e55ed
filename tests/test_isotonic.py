"""Tests for P2.5 — isotonic confidence calibration."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.brain.isotonic import (
    fit_calibrator,
    get_calibrated_confidence,
    get_calibration_summary,
    mark_calibrated,
)
from engine.core.database import Database


def _seed(
    db: Database,
    forecast_id: str,
    producer_name: str,
    confidence: float,
    outcome: float,
    asset: str = "BTC",
    regime: str = "unknown",
) -> None:
    db.conn.execute(
        """
        INSERT INTO forecast_calibration
            (forecast_id, producer_name, asset, regime, horizon, direction,
             confidence, outcome, brier_score, emitted_at, resolved_at)
        VALUES (?, ?, ?, ?, '24h', 'bullish', ?, ?,
                (? - ?) * (? - ?),
                datetime('now','-2 days'), datetime('now','-1 day'))
        """,
        (
            forecast_id,
            producer_name,
            asset,
            regime,
            confidence,
            outcome,
            confidence,
            outcome,
            confidence,
            outcome,
        ),
    )
    db.conn.commit()


@pytest.fixture()
def idb(temp_dir: Path) -> Database:
    db = Database(temp_dir / "brain.db")
    try:
        yield db
    finally:
        db.close()


def test_fit_calibrator_returns_none_when_fewer_than_min_samples(idb: Database) -> None:
    for i in range(19):
        _seed(
            idb,
            forecast_id=f"few-{i}",
            producer_name="p-few",
            confidence=0.5 + (i * 0.02),
            outcome=float(i % 2),
            regime="unknown",
        )

    calibrator = fit_calibrator(idb, producer_name="p-few", regime="unknown", min_samples=20)
    assert calibrator is None


def test_fit_calibrator_returns_knot_dict_when_enough_samples(idb: Database) -> None:
    for i in range(20):
        confidence = 0.5 + (i * 0.02)
        outcome = 1.0 if confidence >= 0.7 else 0.0
        _seed(idb, f"enough-{i}", "p-enough", confidence, outcome, regime="trend")

    calibrator = fit_calibrator(idb, producer_name="p-enough", regime="trend", min_samples=20)

    assert calibrator is not None
    assert set(calibrator.keys()) == {"x", "y"}
    assert len(calibrator["x"]) > 0
    assert len(calibrator["x"]) == len(calibrator["y"])
    assert calibrator["x"] == sorted(calibrator["x"])


def test_get_calibrated_confidence_is_monotone_for_sorted_inputs(idb: Database) -> None:
    for i in range(30):
        confidence = 0.5 + (i * 0.015)
        outcome = float((i * 7) % 5 in {0, 1})
        _seed(idb, f"mono-{i}", "p-mono", confidence, outcome, regime="chop")

    calibrator = fit_calibrator(idb, producer_name="p-mono", regime="chop", min_samples=20)
    assert calibrator is not None

    raw_values = [0.5 + (i * 0.01) for i in range(51)]
    calibrated_values = [get_calibrated_confidence(raw, calibrator) for raw in raw_values]

    for prev, curr in zip(calibrated_values, calibrated_values[1:], strict=False):
        assert curr >= prev


def test_get_calibrated_confidence_returns_raw_when_calibrator_is_none() -> None:
    raw = 0.73
    assert get_calibrated_confidence(raw, None) == pytest.approx(raw)


def test_get_calibrated_confidence_clamps_to_lower_bound() -> None:
    calibrator = {"x": [0.5, 1.0], "y": [0.0, 0.2]}
    assert get_calibrated_confidence(0.8, calibrator) == pytest.approx(0.5)


def test_get_calibrated_confidence_clamps_to_upper_bound() -> None:
    calibrator = {"x": [0.5, 1.0], "y": [1.2, 1.5]}
    assert get_calibrated_confidence(0.8, calibrator) == pytest.approx(1.0)


def test_mark_calibrated_updates_only_requested_rows(idb: Database) -> None:
    _seed(idb, "mark-1", "p-mark", 0.65, 1.0)
    _seed(idb, "mark-2", "p-mark", 0.70, 0.0)
    _seed(idb, "mark-3", "p-mark", 0.75, 1.0)

    updated = mark_calibrated(idb, ["mark-1", "mark-3"])
    assert updated == 2

    rows = idb.conn.execute("SELECT forecast_id, calibrated FROM forecast_calibration WHERE producer_name = 'p-mark' ORDER BY forecast_id").fetchall()
    by_id = {str(row[0]): int(row[1]) for row in rows}

    assert by_id["mark-1"] == 1
    assert by_id["mark-2"] == 0
    assert by_id["mark-3"] == 1


def test_mark_calibrated_returns_zero_for_empty_input(idb: Database) -> None:
    assert mark_calibrated(idb, []) == 0


def test_get_calibration_summary_returns_expected_structure(idb: Database) -> None:
    bull_ids: list[str] = []
    bear_ids: list[str] = []

    for i in range(20):
        forecast_id = f"sum-bull-{i}"
        bull_ids.append(forecast_id)
        confidence = 0.5 + (i * 0.02)
        outcome = 1.0 if i % 3 != 0 else 0.0
        _seed(idb, forecast_id, "p-summary", confidence, outcome, regime="bull")

    for i in range(5):
        forecast_id = f"sum-bear-{i}"
        bear_ids.append(forecast_id)
        confidence = 0.55 + (i * 0.03)
        outcome = float(i % 2)
        _seed(idb, forecast_id, "p-summary", confidence, outcome, regime="bear")

    for i in range(10):
        _seed(idb, f"other-{i}", "p-other", 0.6 + (i * 0.01), float(i % 2), regime="bull")

    mark_calibrated(idb, bull_ids[:3] + bear_ids[:2])

    summary = get_calibration_summary(idb, producer_name="p-summary")

    assert set(summary.keys()) == {"bear", "bull"}
    assert set(summary["bull"].keys()) == {"n_resolved", "n_calibrated", "x_knots", "y_knots"}
    assert summary["bull"]["n_resolved"] == 20
    assert summary["bull"]["n_calibrated"] == 3
    assert len(summary["bull"]["x_knots"]) > 0
    assert len(summary["bull"]["x_knots"]) == len(summary["bull"]["y_knots"])

    assert summary["bear"]["n_resolved"] == 5
    assert summary["bear"]["n_calibrated"] == 2
    assert summary["bear"]["x_knots"] == []
    assert summary["bear"]["y_knots"] == []


def test_edge_case_all_wins_returns_full_confidence(idb: Database) -> None:
    for i in range(20):
        _seed(idb, f"win-{i}", "p-win", 0.5 + (i * 0.02), 1.0, regime="allwins")

    calibrator = fit_calibrator(idb, producer_name="p-win", regime="allwins", min_samples=20)
    assert calibrator is not None
    assert all(y == pytest.approx(1.0) for y in calibrator["y"])
    assert get_calibrated_confidence(0.62, calibrator) == pytest.approx(1.0)


def test_edge_case_all_losses_returns_floor_after_clamp(idb: Database) -> None:
    for i in range(20):
        _seed(idb, f"loss-{i}", "p-loss", 0.5 + (i * 0.02), 0.0, regime="allloss")

    calibrator = fit_calibrator(idb, producer_name="p-loss", regime="allloss", min_samples=20)
    assert calibrator is not None
    assert all(y == pytest.approx(0.0) for y in calibrator["y"])
    assert get_calibrated_confidence(0.88, calibrator) == pytest.approx(0.5)


def test_fit_calibrator_mixed_producers_are_isolated(idb: Database) -> None:
    for i in range(25):
        confidence = 0.5 + (i * 0.015)
        _seed(idb, f"a-{i}", "p-a", confidence, 1.0, regime="mix")
        _seed(idb, f"b-{i}", "p-b", confidence, 0.0, regime="mix")

    cal_a = fit_calibrator(idb, producer_name="p-a", regime="mix", min_samples=20)
    cal_b = fit_calibrator(idb, producer_name="p-b", regime="mix", min_samples=20)

    assert cal_a is not None
    assert cal_b is not None

    pred_a = get_calibrated_confidence(0.8, cal_a)
    pred_b = get_calibrated_confidence(0.8, cal_b)

    assert pred_a > pred_b
    assert pred_a == pytest.approx(1.0)
    assert pred_b == pytest.approx(0.5)


def test_fit_calibrator_respects_asset_filter(idb: Database) -> None:
    for i in range(20):
        confidence = 0.5 + (i * 0.02)
        _seed(idb, f"btc-{i}", "p-asset", confidence, 1.0, asset="BTC", regime="r1")
        _seed(idb, f"eth-{i}", "p-asset", confidence, 0.0, asset="ETH", regime="r1")

    btc = fit_calibrator(idb, producer_name="p-asset", asset="BTC", regime="r1", min_samples=20)
    eth = fit_calibrator(idb, producer_name="p-asset", asset="ETH", regime="r1", min_samples=20)

    assert btc is not None
    assert eth is not None

    assert get_calibrated_confidence(0.75, btc) == pytest.approx(1.0)
    assert get_calibrated_confidence(0.75, eth) == pytest.approx(0.5)
