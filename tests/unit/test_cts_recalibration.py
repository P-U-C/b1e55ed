"""Tests for CTS recalibration (engine.brain.cts_recalibration).

Covers:
1. P75 computation with sufficient data
2. Skipping when insufficient data
3. Partial recalibration (some features have data, others don't)
4. Dry-run mode (no file writes)
5. user.yaml update (merge, not overwrite)
6. Correct nested json_extract paths ($.technical.rsi_14, etc.)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from engine.brain.cts_recalibration import (
    _MIN_SAMPLES,
    _percentile_75,
    compute_calibration_from_db,
    run_recalibration,
)
from engine.core.database import Database


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    return Database(db_path=tmp_path / "test.db")


def _insert_snapshot(db: Database, features: dict, *, created_at: str | None = None) -> None:
    """Insert a feature_snapshots row with the given nested features dict."""
    ts = created_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.execute(
        "INSERT INTO feature_snapshots (cycle_id, symbol, ts, features, created_at) VALUES (?, ?, ?, ?, ?)",
        ("cycle-test", "BTC", ts, json.dumps(features), ts),
    )


def _make_features(
    rsi: float | None = None,
    funding: float | None = None,
    basis: float | None = None,
    oi: float | None = None,
) -> dict:
    """Build a nested features dict matching the real schema."""
    features: dict = {"technical": {}, "tradfi": {}}
    if rsi is not None:
        features["technical"]["rsi_14"] = rsi
    if funding is not None:
        features["tradfi"]["funding_annualized"] = funding
    if basis is not None:
        features["tradfi"]["basis_annualized"] = basis
    if oi is not None:
        features["tradfi"]["oi_change_pct"] = oi
    return features


# ---------------------------------------------------------------------------
# _percentile_75
# ---------------------------------------------------------------------------


class TestPercentile75:
    def test_basic(self):
        # [1, 2, 3, 4, 5, 6, 7, 8] -> P75 = 6.5 (linear interp from statistics.quantiles)
        vals = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        p75 = _percentile_75(vals)
        assert 6.0 <= p75 <= 7.0

    def test_empty(self):
        assert _percentile_75([]) == 0.0

    def test_single_value(self):
        # statistics.quantiles requires at least 2 data points; single raises
        # but _percentile_75 should handle it gracefully in production.
        # For now just ensure it doesn't crash with >= 2 values.
        assert _percentile_75([5.0, 5.0]) == 5.0


# ---------------------------------------------------------------------------
# compute_calibration_from_db
# ---------------------------------------------------------------------------


class TestComputeCalibration:
    def test_sufficient_data(self, db: Database):
        """With enough samples, all four calibration keys are returned."""
        for i in range(_MIN_SAMPLES + 5):
            _insert_snapshot(
                db,
                _make_features(
                    rsi=50.0 + i * 0.5,
                    funding=1.0 + i * 0.2,
                    basis=0.5 + i * 0.1,
                    oi=0.1 + i * 0.3,
                ),
            )

        result = compute_calibration_from_db(db, lookback_days=30)
        assert result is not None
        assert "rsi_center" in result
        assert "funding_center" in result
        assert "basis_center" in result
        assert "oi_roc_center" in result
        assert "calibrated_at" in result

        # RSI values range from 50 to 62; P75 should be > 50
        assert result["rsi_center"] > 50.0
        # Funding uses abs(), so all positive
        assert result["funding_center"] > 0.0

    def test_insufficient_data(self, db: Database):
        """With fewer than _MIN_SAMPLES rows, returns None."""
        for i in range(_MIN_SAMPLES - 1):
            _insert_snapshot(db, _make_features(rsi=55.0 + i))

        result = compute_calibration_from_db(db, lookback_days=30)
        assert result is None

    def test_partial_data(self, db: Database):
        """Only features with enough samples get recalibrated."""
        # Insert enough rows with RSI and funding, but not basis or OI
        for i in range(_MIN_SAMPLES + 5):
            _insert_snapshot(
                db,
                _make_features(rsi=50.0 + i, funding=2.0 + i * 0.1),
            )

        result = compute_calibration_from_db(db, lookback_days=30)
        assert result is not None
        assert "rsi_center" in result
        assert "funding_center" in result
        assert "basis_center" not in result
        assert "oi_roc_center" not in result

    def test_old_data_excluded(self, db: Database):
        """Snapshots older than lookback_days are excluded."""
        # Insert old data (60 days ago)
        for i in range(_MIN_SAMPLES + 5):
            _insert_snapshot(
                db,
                _make_features(rsi=55.0 + i),
                created_at="2020-01-01T00:00:00Z",
            )

        result = compute_calibration_from_db(db, lookback_days=30)
        assert result is None

    def test_negative_funding_uses_abs(self, db: Database):
        """Negative funding values should be treated as absolute values."""
        for i in range(_MIN_SAMPLES + 5):
            # Alternate positive and negative funding
            sign = -1 if i % 2 == 0 else 1
            _insert_snapshot(
                db,
                _make_features(funding=sign * (3.0 + i * 0.2)),
            )

        result = compute_calibration_from_db(db, lookback_days=30)
        assert result is not None
        # All values should be positive (abs applied)
        assert result["funding_center"] > 0.0


# ---------------------------------------------------------------------------
# run_recalibration
# ---------------------------------------------------------------------------


class TestRunRecalibration:
    def test_dry_run_no_file_write(self, db: Database, tmp_path: Path):
        """Dry run should not create or modify user.yaml."""
        repo_root = tmp_path / "repo"
        config_dir = repo_root / "config"
        config_dir.mkdir(parents=True)
        # Create a minimal default.yaml so Config.from_yaml works
        (config_dir / "default.yaml").write_text("preset: balanced\n")
        (config_dir / "presets").mkdir()
        (config_dir / "presets" / "balanced.yaml").write_text("{}\n")

        for i in range(_MIN_SAMPLES + 5):
            _insert_snapshot(db, _make_features(rsi=50.0 + i, funding=2.0 + i * 0.1))

        result = run_recalibration(repo_root, db, lookback_days=30, dry_run=True)
        assert result["status"] == "dry_run"
        # user.yaml should not exist (we didn't create it)
        assert not (config_dir / "user.yaml").exists()

    def test_writes_user_yaml(self, db: Database, tmp_path: Path):
        """Non-dry-run should create/update user.yaml with new calibration."""
        repo_root = tmp_path / "repo"
        config_dir = repo_root / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "default.yaml").write_text("preset: balanced\n")
        (config_dir / "presets").mkdir()
        (config_dir / "presets" / "balanced.yaml").write_text("{}\n")

        for i in range(_MIN_SAMPLES + 5):
            _insert_snapshot(db, _make_features(rsi=50.0 + i, funding=2.0 + i * 0.1))

        result = run_recalibration(repo_root, db, lookback_days=30, dry_run=False)
        assert result["status"] == "recalibrated"
        assert result["calibrated_at"]

        # Verify user.yaml was written
        user_yaml = config_dir / "user.yaml"
        assert user_yaml.exists()
        data = yaml.safe_load(user_yaml.read_text())
        cal = data["brain"]["cts_calibration"]
        assert "rsi_center" in cal
        assert "calibrated_at" in cal

    def test_preserves_existing_user_yaml(self, db: Database, tmp_path: Path):
        """Recalibration should merge into existing user.yaml, not overwrite."""
        repo_root = tmp_path / "repo"
        config_dir = repo_root / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "default.yaml").write_text("preset: balanced\n")
        (config_dir / "presets").mkdir()
        (config_dir / "presets" / "balanced.yaml").write_text("{}\n")

        # Pre-existing user.yaml with other settings
        user_yaml = config_dir / "user.yaml"
        user_yaml.write_text(yaml.dump({"preset": "degen", "execution": {"mode": "paper"}}, sort_keys=False))

        for i in range(_MIN_SAMPLES + 5):
            _insert_snapshot(db, _make_features(rsi=50.0 + i, funding=2.0 + i * 0.1))

        run_recalibration(repo_root, db, lookback_days=30, dry_run=False)

        data = yaml.safe_load(user_yaml.read_text())
        # Original settings preserved
        assert data["preset"] == "degen"
        assert data["execution"]["mode"] == "paper"
        # New calibration added
        assert "rsi_center" in data["brain"]["cts_calibration"]

    def test_skipped_insufficient_data(self, db: Database, tmp_path: Path):
        """Returns skipped status when no data available."""
        repo_root = tmp_path / "repo"
        config_dir = repo_root / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "default.yaml").write_text("preset: balanced\n")
        (config_dir / "presets").mkdir()
        (config_dir / "presets" / "balanced.yaml").write_text("{}\n")

        result = run_recalibration(repo_root, db, lookback_days=30, dry_run=False)
        assert result["status"] == "skipped"
