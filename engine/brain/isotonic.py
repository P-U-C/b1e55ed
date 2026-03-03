"""
Isotonic calibration for per-producer forecast confidence.

Fits isotonic regression on resolved forecast_calibration rows:
  input  x = raw confidence (0.5–1.0)
  target y = outcome (1.0 = hit, 0.0 = miss)

Calibrated confidence is a monotone-increasing adjustment so that
"0.7 confidence" actually means a ~70% historical win rate.

Shadow mode: calibrated values are written to forecast_calibration.calibrated=1
but the raw confidence is NOT overwritten. Callers must opt in via
get_calibrated_confidence().
"""

from __future__ import annotations

import importlib
from bisect import bisect_right
from typing import Any

_SklearnIsotonicRegression: Any | None
try:
    _sklearn_isotonic = importlib.import_module("sklearn.isotonic")
    _SklearnIsotonicRegression = _sklearn_isotonic.IsotonicRegression
except ModuleNotFoundError:  # pragma: no cover - fallback exercised only when sklearn is absent
    _SklearnIsotonicRegression = None


def _connection(db: Any) -> Any:
    """Accept either a Database object (has .conn) or a raw sqlite3 connection."""
    return getattr(db, "conn", db)


def _clamp_confidence(value: float) -> float:
    return max(0.5, min(1.0, float(value)))


# Pool Adjacent Violators — Brunk (1955); formalized by Barlow, Bartholomew, Bremner & Brunk (1972).
# Zadrozny & Elkan (2002) showed isotonic calibration outperforms sigmoid scaling
# when the calibration data is not well-described by a logistic function.
# The market is not logistic. O(n) is fast enough for the truth.
def _fit_isotonic_fallback(confidences: list[float], outcomes: list[float]) -> tuple[list[float], list[float]]:
    """Minimal weighted PAV isotonic fit used only when sklearn is unavailable."""
    ordered = sorted(zip(confidences, outcomes, strict=False), key=lambda item: item[0])
    if not ordered:
        return [], []

    x_unique: list[float] = []
    y_sum: list[float] = []
    weights: list[float] = []

    for x_val, y_val in ordered:
        x_float = float(x_val)
        y_float = float(y_val)
        if x_unique and x_float == x_unique[-1]:
            y_sum[-1] += y_float
            weights[-1] += 1.0
        else:
            x_unique.append(x_float)
            y_sum.append(y_float)
            weights.append(1.0)

    y_avg = [s / w for s, w in zip(y_sum, weights, strict=False)]

    block_starts: list[int] = []
    block_ends: list[int] = []
    block_sumw: list[float] = []
    block_sumy: list[float] = []

    for i, (y_val, w_val) in enumerate(zip(y_avg, weights, strict=False)):
        block_starts.append(i)
        block_ends.append(i)
        block_sumw.append(float(w_val))
        block_sumy.append(float(y_val) * float(w_val))

        while len(block_sumw) >= 2:
            prev_mean = block_sumy[-2] / block_sumw[-2]
            curr_mean = block_sumy[-1] / block_sumw[-1]
            if prev_mean <= curr_mean:
                break

            block_ends[-2] = block_ends[-1]
            block_sumw[-2] += block_sumw[-1]
            block_sumy[-2] += block_sumy[-1]

            block_starts.pop()
            block_ends.pop()
            block_sumw.pop()
            block_sumy.pop()

    fitted = [0.0] * len(x_unique)
    for start, end, sum_w, sum_y in zip(block_starts, block_ends, block_sumw, block_sumy, strict=False):
        level = sum_y / sum_w
        for idx in range(start, end + 1):
            fitted[idx] = level

    return x_unique, fitted


def fit_calibrator(
    db: Any,
    producer_name: str,
    asset: str = "ALL",
    regime: str = "unknown",
    min_samples: int = 20,
) -> dict[str, list[float]] | None:
    """
    Fit an isotonic calibrator for one producer/asset/regime slice.

    Returns:
        {"x": [knot_x...], "y": [knot_y...]} or None when there is
        insufficient resolved data.
    """
    conn = _connection(db)
    rows = conn.execute(
        """
        SELECT confidence, outcome
        FROM forecast_calibration
        WHERE outcome IS NOT NULL
          AND producer_name = ?
          AND (? = 'ALL' OR asset = ?)
          AND (? = 'unknown' OR regime = ?)
        ORDER BY confidence ASC, id ASC
        """,
        (producer_name, asset, asset, regime, regime),
    ).fetchall()

    if len(rows) < min_samples:
        return None

    confidences = [float(row[0]) for row in rows]
    outcomes = [float(row[1]) for row in rows]

    x_knots: list[float]
    y_knots: list[float]
    if _SklearnIsotonicRegression is not None:
        model = _SklearnIsotonicRegression(out_of_bounds="clip")
        model.fit(confidences, outcomes)
        x_knots = [float(value) for value in model.X_thresholds_]
        y_knots = [float(value) for value in model.y_thresholds_]
    else:  # pragma: no cover - local/dev fallback
        x_knots, y_knots = _fit_isotonic_fallback(confidences, outcomes)

    if not x_knots or not y_knots or len(x_knots) != len(y_knots):
        return None

    return {"x": x_knots, "y": y_knots}


def get_calibrated_confidence(
    raw_confidence: float,
    calibrator_dict: dict[str, list[float]] | None,
) -> float:
    """
    Apply isotonic knots to a raw confidence value.

    Shadow-safe fallback: if no calibrator is available, return raw confidence.
    """
    raw = float(raw_confidence)
    if calibrator_dict is None:
        return raw

    x_knots_raw = calibrator_dict.get("x", [])
    y_knots_raw = calibrator_dict.get("y", [])
    if not x_knots_raw or not y_knots_raw:
        return _clamp_confidence(raw)

    x_knots = [float(x) for x in x_knots_raw]
    y_knots = [float(y) for y in y_knots_raw]
    if len(x_knots) != len(y_knots):
        return _clamp_confidence(raw)

    # Defensive normalization if caller provided unsorted knots.
    ordered_pairs = sorted(zip(x_knots, y_knots, strict=False), key=lambda item: item[0])
    xs = [pair[0] for pair in ordered_pairs]
    ys = [pair[1] for pair in ordered_pairs]

    if raw <= xs[0]:
        return _clamp_confidence(ys[0])
    if raw >= xs[-1]:
        return _clamp_confidence(ys[-1])

    idx = bisect_right(xs, raw)
    left_x = xs[idx - 1]
    right_x = xs[idx]
    left_y = ys[idx - 1]
    right_y = ys[idx]

    if right_x == left_x:
        calibrated = right_y
    else:
        weight = (raw - left_x) / (right_x - left_x)
        calibrated = left_y + (right_y - left_y) * weight

    return _clamp_confidence(calibrated)


def mark_calibrated(db: Any, forecast_ids: list[str]) -> int:
    """Mark forecast_calibration rows as calibrated. Returns rows updated."""
    ids = [str(forecast_id) for forecast_id in forecast_ids if forecast_id]
    if not ids:
        return 0

    conn = _connection(db)
    placeholders = ",".join(["?"] * len(ids))

    with conn:
        cursor = conn.execute(
            f"""
            UPDATE forecast_calibration
            SET calibrated = 1
            WHERE forecast_id IN ({placeholders})
              AND calibrated <> 1
            """,
            ids,
        )

    return int(cursor.rowcount or 0)


def get_calibration_summary(db: Any, producer_name: str) -> dict[str, dict[str, Any]]:
    """
    Return calibration status by regime for one producer.

    Shape:
        {
            "regime": {
                "n_resolved": int,
                "n_calibrated": int,
                "x_knots": list[float],
                "y_knots": list[float],
            }
        }
    """
    conn = _connection(db)
    rows = conn.execute(
        """
        SELECT
            regime,
            COUNT(*) AS n_resolved,
            SUM(CASE WHEN calibrated = 1 THEN 1 ELSE 0 END) AS n_calibrated
        FROM forecast_calibration
        WHERE producer_name = ?
          AND outcome IS NOT NULL
        GROUP BY regime
        ORDER BY regime ASC
        """,
        (producer_name,),
    ).fetchall()

    summary: dict[str, dict[str, Any]] = {}
    for row in rows:
        regime = str(row[0])
        calibrator = fit_calibrator(
            db=db,
            producer_name=producer_name,
            asset="ALL",
            regime=regime,
            min_samples=20,
        )
        summary[regime] = {
            "n_resolved": int(row[1] or 0),
            "n_calibrated": int(row[2] or 0),
            "x_knots": calibrator["x"] if calibrator else [],
            "y_knots": calibrator["y"] if calibrator else [],
        }

    return summary
