"""engine.brain.cts_recalibration

Automated CTS recalibration mechanism.

Reads recent feature_snapshots from brain.db, computes P75 (75th percentile)
values for each CTS calibration parameter, and updates the cts_calibration
section in config/user.yaml.

Features are stored as a nested JSON blob in the ``features`` column:
  - RSI:     ``json_extract(features, '$.technical.rsi_14')``
  - Funding: ``json_extract(features, '$.tradfi.funding_annualized')``
  - Basis:   ``json_extract(features, '$.tradfi.basis_annualized')``
  - OI:      ``json_extract(features, '$.tradfi.oi_change_pct')``

Designed to run as a daemon scheduler task every ``recalibrate_interval_days``
days, or manually via ``b1e55ed recalibrate-cts``.
"""

from __future__ import annotations

import logging
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from engine.core.database import Database

logger = logging.getLogger("b1e55ed.cts_recalibration")

# Minimum number of non-null samples required per feature to recalibrate.
# Below this threshold we keep the existing (or default) calibration for that feature.
_MIN_SAMPLES = 20

# Feature extraction paths within the JSON blob stored in feature_snapshots.features.
# key: calibration parameter name -> (json_extract path, use_abs)
_FEATURE_SPEC: dict[str, tuple[str, bool]] = {
    "rsi_center": ("$.technical.rsi_14", False),
    "funding_center": ("$.tradfi.funding_annualized", True),
    "basis_center": ("$.tradfi.basis_annualized", True),
    "oi_roc_center": ("$.tradfi.oi_change_pct", True),
}


def _percentile_75(values: list[float]) -> float:
    """Compute the 75th percentile using the nearest-rank method."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    # statistics.quantiles(data, n=4) returns [Q1, Q2, Q3].
    quartiles = statistics.quantiles(sorted_vals, n=4)
    return quartiles[2]  # Q3 = P75


def _query_feature_values(
    db: Database,
    json_path: str,
    lookback_days: int,
    *,
    use_abs: bool = False,
) -> list[float]:
    """Extract non-null numeric feature values from recent snapshots via json_extract."""
    extract = f"json_extract(features, '{json_path}')"
    value_expr = f"ABS({extract})" if use_abs else extract
    cutoff = f"-{lookback_days} days"

    rows = db.fetchall(
        f"SELECT {value_expr} AS val FROM feature_snapshots "  # noqa: S608
        f"WHERE created_at > datetime('now', ?) "
        f"AND {extract} IS NOT NULL "
        f"AND typeof({extract}) IN ('integer', 'real')",
        (cutoff,),
    )
    return [float(r[0]) for r in rows]


def compute_calibration_from_db(
    db: Database,
    lookback_days: int = 30,
) -> dict[str, Any] | None:
    """Query feature_snapshots for the last ``lookback_days`` days and compute
    P75 values for CTS calibration parameters.

    Returns a dict with keys ``rsi_center``, ``funding_center``,
    ``basis_center``, ``oi_roc_center``, ``calibrated_at`` — or None if
    insufficient data for every feature.
    """
    result: dict[str, Any] = {}
    sample_counts: dict[str, int] = {}

    for key, (json_path, use_abs) in _FEATURE_SPEC.items():
        values = _query_feature_values(db, json_path, lookback_days, use_abs=use_abs)
        sample_counts[key] = len(values)
        if len(values) >= _MIN_SAMPLES:
            result[key] = round(_percentile_75(values), 2)
            logger.info("Recalibration %s: P75=%.2f (n=%d)", key, result[key], len(values))
        else:
            logger.info(
                "Insufficient data for %s: %d samples (need %d). Keeping current value.",
                key,
                len(values),
                _MIN_SAMPLES,
            )

    if not result:
        logger.info("No feature had enough samples for recalibration. Skipping.")
        return None

    result["calibrated_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    result["_sample_counts"] = sample_counts
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

    sample_counts = new_cal.pop("_sample_counts", {})
    calibrated_at = new_cal.get("calibrated_at", "")
    new_values = {k: v for k, v in new_cal.items() if k != "calibrated_at"}

    summary: dict[str, Any] = {
        "status": "recalibrated",
        "old": {k: old_cal.get(k) for k in new_values},
        "new": new_values,
        "calibrated_at": calibrated_at,
        "lookback_days": lookback_days,
        "sample_counts": sample_counts,
    }

    if dry_run:
        summary["status"] = "dry_run"
        logger.info("Dry run — would update calibration: %s", summary["new"])
    else:
        _update_user_yaml(user_yaml_path, new_cal)
        logger.info(
            "CTS recalibration complete. Old: %s -> New: %s",
            summary["old"],
            summary["new"],
        )

    return summary
