"""Pairwise correlation tracking between producer conviction outputs.

Measures rolling 30-day Pearson correlation between producer score series.
Correlation is TRACKED first, not penalized. The spec says: "you don't know
your distributions yet and pretending you do is worse than admitting you
don't."

This module writes to ``producer_correlation`` but does NOT modify synthesis
weights. That is a P4 responsibility.

Correlation is computed from ``conviction_log`` (append-only producer
contribution records). It depends on ``conviction_log.producer_name`` (added in
P0B); old schemas without that column return no correlation rows.
"""

from __future__ import annotations

import logging
import math
import sqlite3
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _conn(db: Any) -> sqlite3.Connection:
    return db.conn if hasattr(db, "conn") else db


def _table_exists(db: Any, table: str) -> bool:
    conn = _conn(db)
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _has_column(db: Any, table: str, column: str) -> bool:
    conn = _conn(db)
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(str(r[1]) == column for r in rows)


def _pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    """Pearson correlation coefficient. Returns None if std dev is 0."""
    if len(xs) != len(ys):
        return None

    n = len(xs)
    if n < 3:
        return None

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    std_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    std_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if std_x == 0 or std_y == 0:
        return None
    return cov / (std_x * std_y)


def update_correlation_pair(
    db: Any,
    producer_a: str,
    producer_b: str,
    asset: str = "ALL",
    regime: str = "unknown",
    window_days: int = 30,
) -> Optional[float]:
    """Compute and store rolling N-day Pearson correlation between two producers.

    Scores are derived from hourly buckets of ``conviction_log.weighted_contribution``.
    Regime is currently persisted as metadata in ``producer_correlation`` (the
    source log does not yet have a regime column for filtering).
    """
    conn = _conn(db)

    if not _table_exists(conn, "producer_correlation"):
        logger.debug("producer_correlation table missing; skipping")
        return None

    if not _has_column(conn, "conviction_log", "producer_name"):
        logger.debug("conviction_log.producer_name missing (pre-P0B schema); skipping")
        return None

    query = """
        SELECT
            strftime('%Y-%m-%dT%H:00', ts) AS hour_bucket,
            AVG(weighted_contribution) AS avg_score
        FROM conviction_log
        WHERE producer_name = ?
          AND (? = 'ALL' OR symbol = ?)
          AND datetime(ts) >= datetime('now', ? || ' days')
        GROUP BY hour_bucket
        ORDER BY hour_bucket ASC
    """

    window_param = f"-{window_days}"
    rows_a = {
        str(r[0]): float(r[1])
        for r in conn.execute(query, (producer_a, asset, asset, window_param)).fetchall()
        if r[0] is not None and r[1] is not None
    }
    rows_b = {
        str(r[0]): float(r[1])
        for r in conn.execute(query, (producer_b, asset, asset, window_param)).fetchall()
        if r[0] is not None and r[1] is not None
    }

    common_hours = sorted(set(rows_a.keys()) & set(rows_b.keys()))
    if len(common_hours) < 3:
        return None

    xs = [rows_a[h] for h in common_hours]
    ys = [rows_b[h] for h in common_hours]
    r = _pearson(xs, ys)

    with conn:
        conn.execute(
            """
            INSERT INTO producer_correlation
                (producer_a, producer_b, asset, regime, pearson_r,
                 sample_count, window_days, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(producer_a, producer_b, asset, regime)
            DO UPDATE SET
                pearson_r    = excluded.pearson_r,
                sample_count = excluded.sample_count,
                window_days  = excluded.window_days,
                last_updated = excluded.last_updated
            """,
            (producer_a, producer_b, asset, regime, r, len(common_hours), window_days),
        )

    return r


def update_all_pairs(
    db: Any,
    asset: str = "ALL",
    regime: str = "unknown",
    window_days: int = 30,
) -> dict[tuple[str, str], Optional[float]]:
    """Compute correlation for every producer pair found in conviction_log."""
    conn = _conn(db)

    if not _has_column(conn, "conviction_log", "producer_name"):
        return {}

    producers = [
        str(r[0])
        for r in conn.execute(
            """
            SELECT DISTINCT producer_name
            FROM conviction_log
            WHERE producer_name IS NOT NULL
              AND producer_name != ''
              AND (? = 'ALL' OR symbol = ?)
            ORDER BY producer_name ASC
            """,
            (asset, asset),
        ).fetchall()
    ]

    results: dict[tuple[str, str], Optional[float]] = {}
    for i, a in enumerate(producers):
        for b in producers[i + 1 :]:
            results[(a, b)] = update_correlation_pair(db, a, b, asset, regime, window_days)

    return results


def get_correlation_matrix(db: Any) -> list[dict[str, Any]]:
    """Return all stored correlation rows."""
    conn = _conn(db)

    if not _table_exists(conn, "producer_correlation"):
        return []

    rows = conn.execute(
        """
        SELECT producer_a, producer_b, asset, regime, pearson_r,
               sample_count, window_days, last_updated
        FROM producer_correlation
        ORDER BY producer_a, producer_b
        """
    ).fetchall()

    return [
        {
            "producer_a": str(r[0]),
            "producer_b": str(r[1]),
            "asset": str(r[2]),
            "regime": str(r[3]),
            "pearson_r": float(r[4]) if r[4] is not None else None,
            "sample_count": int(r[5]),
            "window_days": int(r[6]),
            "last_updated": str(r[7]),
        }
        for r in rows
    ]
