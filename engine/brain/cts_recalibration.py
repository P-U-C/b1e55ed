"""engine.brain.cts_recalibration

Automated CTS recalibration mechanism.

Reads recent feature_snapshots from brain.db, computes P75 (75th percentile)
values for each CTS calibration parameter, and updates the cts_calibration
section in config/user.yaml.

Designed to run as a daemon scheduler task every ``recalibrate_interval_days``
days, or manually via ``b1e55ed recalibrate-cts``.
"""

from __future__ import annotations

import json
import logging
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.core.database import Database

logger = logging.getLogger("b1e55ed.cts_recalibration")

# Minimum number of feature snapshots required to recalibrate.
# Below this threshold we keep the existing (or default) calibration.
_MIN_SAMPLES = 20


def _percentile_75(values: list[float]) -> float:
    """Compute the 75th percentile using the nearest-rank method."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    # Use statistics.quantiles (Python 3.8+) for a clean implementation.
    # quantiles(data, n=4) returns [Q1, Q2, Q3].
    quartiles = statistics.quantiles(sorted_vals, n=4)
    return quartiles[2]  # Q3 = P75


def compute_calibration_from_db(
    db: Database,
    lookback_days: int = 30,
) -> dict[str, Any] | None:
    """Query feature_snapshots for the last ``lookback_days`` days and compute
    P75 values for CTS calibration parameters.

    Returns a dict with keys ``rsi_center``, ``funding_center``,
    ``basis_center``, ``oi_roc_center``, ``calibrated_at`` — or None if
    insufficient data.
    """
    cutoff = f"-{lookback_days} days"
    rows = db.execute(
        "SELECT features FROM feature_snapshots WHERE created_at > datetime('now', ?)",
        (cutoff,),
    ).fetchall()

    if len(rows) < _MIN_SAMPLES:
        logger.info(
            "Insufficient data for recalibration: %d snapshots (need %d). Skipping.",
            len(rows),
            _MIN_SAMPLES,
        )
        return None

    rsi_values: list[float] = []
    funding_values: list[float] = []
    basis_values: list[float] = []
    oi_values: list[float] = []

    for row in rows:
        try:
            features = json.loads(row["features"]) if isinstance(row["features"], str) else row["features"]
        except (json.JSONDecodeError, TypeError):
            continue

        if features.get("rsi_14") is not None:
            rsi_values.append(float(features["rsi_14"]))
        if features.get("funding_annualized") is not None:
            funding_values.append(abs(float(features["funding_annualized"])))
        if features.get("basis_annualized") is not None:
            basis_values.append(abs(float(features["basis_annualized"])))
        if features.get("oi_change_pct") is not None:
            oi_values.append(abs(float(features["oi_change_pct"])))

    result: dict[str, Any] = {}

    if len(rsi_values) >= _MIN_SAMPLES:
        result["rsi_center"] = round(_percentile_75(rsi_values), 2)
    if len(funding_values) >= _MIN_SAMPLES:
        result["funding_center"] = round(_percentile_75(funding_values), 2)
    if len(basis_values) >= _MIN_SAMPLES:
        result["basis_center"] = round(_percentile_75(basis_values), 2)
    if len(oi_values) >= _MIN_SAMPLES:
        result["oi_roc_center"] = round(_percentile_75(oi_values), 2)

    if not result:
        logger.info("No feature had enough samples for recalibration. Skipping.")
        return None

    result["calibrated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return result


def _update_user_yaml(user_yaml_path: Path, new_cal: dict[str, Any]) -> None:
    """Merge new calibration values into the user.yaml config file."""
    if user_yaml_path.exists():
        raw = yaml.safe_load(user_yaml_path.read_text(encoding="utf-8")) or {}
    else:
        raw = {}

    brain = raw.setdefault("brain", {})
    cts_cal = brain.setdefault("cts_calibration", {})

    for key, value in new_cal.items():
        cts_cal[key] = value

    user_yaml_path.parent.mkdir(parents=True, exist_ok=True)
    user_yaml_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


def run_recalibration(
    repo_root: Path,
    db: Database,
    *,
    lookback_days: int = 30,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run the full recalibration pipeline.

    Returns a summary dict with old values, new values, and status.
    """
    user_yaml_path = repo_root / "config" / "user.yaml"

    # Read current calibration
    old_cal: dict[str, Any] = {}
    if user_yaml_path.exists():
        raw = yaml.safe_load(user_yaml_path.read_text(encoding="utf-8")) or {}
        old_cal = raw.get("brain", {}).get("cts_calibration", {})

    new_cal = compute_calibration_from_db(db, lookback_days=lookback_days)

    if new_cal is None:
        return {"status": "skipped", "reason": "insufficient_data"}

    summary = {
        "status": "recalibrated",
        "old": {k: old_cal.get(k) for k in new_cal if k != "calibrated_at"},
        "new": {k: v for k, v in new_cal.items() if k != "calibrated_at"},
        "calibrated_at": new_cal["calibrated_at"],
        "lookback_days": lookback_days,
    }

    if dry_run:
        summary["status"] = "dry_run"
        logger.info("Dry run — would update calibration: %s", summary["new"])
    else:
        _update_user_yaml(user_yaml_path, new_cal)
        logger.info(
            "CTS recalibration complete. Updated %s -> %s",
            summary["old"],
            summary["new"],
        )

    return summary
