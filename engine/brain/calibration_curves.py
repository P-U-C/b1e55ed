"""
Per-producer calibration curves.

Allan Murphy, 1977. "The value of climatological, categorical, and
probabilistic forecasts in the cost-loss ratio situation."
The reliability diagram appeared here before anyone called it that.
A perfectly calibrated forecaster lies on the diagonal y = x.
No forecaster lies on the diagonal y = x.

Aggregates resolved Brier scores from forecast_calibration into
bucketed calibration rows in producer_calibration.

When a producer says "0.7 confidence", this tells you whether its
historical win rate in that bucket actually justified that confidence.

Shadow mode: this data is READ by the weighting system but does NOT
affect live conviction weights until P4 explicitly enables it.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Shannon: information is the resolution of uncertainty.
# A bucket that is always right reduces uncertainty completely.
# A bucket that is always wrong is also informative — just not in the direction claimed.
CONFIDENCE_BUCKETS = [
    ("0.5-0.6", 0.5, 0.6),
    ("0.6-0.7", 0.6, 0.7),
    ("0.7-0.8", 0.7, 0.8),
    ("0.8-0.9", 0.8, 0.9),
    ("0.9+", 0.9, 1.01),
]


def _connection(db: Any) -> Any:
    """Accept either a Database object (has .conn) or a raw sqlite3 connection."""
    return getattr(db, "conn", db)


def update_calibration_curves(
    db: Any,
    producer_name: str,
    asset: str = "ALL",
    regime: str = "unknown",
) -> list[dict[str, Any]]:
    """
    Recompute calibration curve rows for a (producer, asset, regime) tuple.
    Reads from forecast_calibration, writes to producer_calibration.
    Returns the updated rows.
    """
    conn = _connection(db)
    updated: list[dict[str, Any]] = []

    with conn:
        for bucket_label, low, high in CONFIDENCE_BUCKETS:
            rows = conn.execute(
                """
                SELECT outcome, brier_score, confidence
                FROM forecast_calibration
                WHERE producer_name = ?
                  AND (? = 'ALL' OR asset = ?)
                  AND (? = 'unknown' OR regime = ?)
                  AND confidence >= ? AND confidence < ?
                  AND resolved_at IS NOT NULL
                """,
                (producer_name, asset, asset, regime, regime, low, high),
            ).fetchall()

            if not rows:
                continue

            sample_count = len(rows)
            win_rate = sum(1 for r in rows if r[0] is not None and float(r[0]) == 1.0) / sample_count
            brier_values = [float(r[1]) for r in rows if r[1] is not None]
            mean_brier = sum(brier_values) / len(brier_values) if brier_values else 0.0

            conn.execute(
                """
                INSERT INTO producer_calibration
                    (producer_name, asset, regime, confidence_bucket,
                     observed_win_rate, mean_brier_score, sample_count, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(producer_name, asset, regime, confidence_bucket)
                DO UPDATE SET
                    observed_win_rate = excluded.observed_win_rate,
                    mean_brier_score  = excluded.mean_brier_score,
                    sample_count      = excluded.sample_count,
                    last_updated      = excluded.last_updated
                """,
                (producer_name, asset, regime, bucket_label, round(win_rate, 4), round(mean_brier, 4), sample_count),
            )

            updated.append(
                {
                    "bucket": bucket_label,
                    "sample_count": sample_count,
                    "observed_win_rate": round(win_rate, 4),
                    "mean_brier_score": round(mean_brier, 4),
                }
            )

    return updated


def get_calibration_curve(
    db: Any,
    producer_name: str,
    asset: str = "ALL",
    regime: str = "unknown",
) -> list[dict[str, Any]]:
    """
    Return the stored calibration curve for a producer.
    Returns sorted list of bucket dicts.
    """
    conn = _connection(db)
    rows = conn.execute(
        """
        SELECT confidence_bucket, observed_win_rate, mean_brier_score,
               sample_count, last_updated
        FROM producer_calibration
        WHERE producer_name = ?
          AND asset = ?
          AND regime = ?
        ORDER BY confidence_bucket ASC
        """,
        (producer_name, asset, regime),
    ).fetchall()

    return [
        {
            "bucket": row[0],
            "observed_win_rate": row[1],
            "mean_brier_score": row[2],
            "sample_count": row[3],
            "last_updated": row[4],
        }
        for row in rows
    ]


def is_well_calibrated(db: Any, producer_name: str, min_samples: int = 10) -> bool:
    """
    Return True if the producer has at least one bucket with min_samples.
    Used as a guard before trusting calibration data for weighting.
    """
    conn = _connection(db)
    row = conn.execute(
        """
        SELECT MAX(sample_count)
        FROM producer_calibration
        WHERE producer_name = ?
        """,
        (producer_name,),
    ).fetchone()
    return (row[0] or 0) >= min_samples
