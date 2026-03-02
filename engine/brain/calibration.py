"""
Brier score tracking and forecast resolution.

Resolution logic: when a forecast's horizon expires, compare the
emitted direction (bullish/bearish) to actual price movement.
Outcome = 1.0 if direction was correct, 0.0 if wrong.
Brier score = (confidence - outcome)^2.

This module only READS price data and WRITES to forecast_calibration.
It never touches live signals or conviction scores.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    UTC = UTC  # noqa: N806

from typing import Any

logger = logging.getLogger(__name__)

# Horizon string -> minutes
HORIZON_MINUTES: dict[str, int] = {
    "15m": 15,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
    "3d": 4320,
    "7d": 10080,
}


@dataclass(frozen=True, slots=True)
class CalibrationRecord:
    forecast_id: str
    producer_name: str
    asset: str
    regime: str
    horizon: str
    direction: str  # bullish | bearish | neutral
    confidence: float
    emitted_at: str
    outcome: float | None = None
    brier_score: float | None = None
    resolved_at: str | None = None
    calibrated: bool = False


def _connection(db: Any) -> Any:
    """Resolve sqlite3.Connection from Database or raw connection."""
    return getattr(db, "conn", db)


def _parse_iso_utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def register_forecast(
    db: Any,
    forecast_id: str,
    producer_name: str,
    asset: str,
    regime: str,
    horizon: str,
    direction: str,
    confidence: float,
    emitted_at: str,
    price_at_emit: float | None = None,
) -> None:
    """
    Register a new forecast for calibration tracking.
    Called by emit_forecast() immediately after FORECAST_V1 event is stored.
    Idempotent -- safe to call twice on same forecast_id.
    """
    conn = _connection(db)
    try:
        with conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO forecast_calibration
                    (forecast_id, producer_name, asset, regime, horizon, direction,
                     confidence, emitted_at, price_at_emit)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    forecast_id,
                    producer_name,
                    asset,
                    regime,
                    horizon,
                    direction,
                    confidence,
                    emitted_at,
                    price_at_emit,
                ),
            )
    except Exception as e:  # noqa: BLE001
        logger.error("register_forecast failed for %s: %s", forecast_id, e)


def resolve_forecast(
    db: Any,
    forecast_id: str,
    outcome: float,
    price_at_resolve: float | None = None,
) -> None:
    """
    Record the outcome of a forecast and compute its Brier score.
    outcome: 1.0 = direction was correct, 0.0 = wrong.
    Brier score = (confidence - outcome)^2.
    """
    conn = _connection(db)
    try:
        row = conn.execute(
            "SELECT confidence FROM forecast_calibration WHERE forecast_id = ?",
            (forecast_id,),
        ).fetchone()
        if row is None:
            logger.warning("resolve_forecast: unknown forecast_id %s", forecast_id)
            return

        confidence = float(row[0])
        brier = (confidence - float(outcome)) ** 2
        now = datetime.now(tz=UTC).isoformat()

        with conn:
            conn.execute(
                """
                UPDATE forecast_calibration
                SET outcome = ?, brier_score = ?, price_at_resolve = ?, resolved_at = ?
                WHERE forecast_id = ?
                  AND resolved_at IS NULL
                """,
                (float(outcome), brier, price_at_resolve, now, forecast_id),
            )
    except Exception as e:  # noqa: BLE001
        logger.error("resolve_forecast failed for %s: %s", forecast_id, e)


def get_pending_resolution(db: Any, max_age_minutes: int = 10080) -> list[CalibrationRecord]:
    """
    Return forecasts whose horizon has elapsed but are still unresolved.
    max_age_minutes guards against very old forecasts being resolved stale.
    """
    conn = _connection(db)
    rows = conn.execute(
        """
        SELECT forecast_id, producer_name, asset, regime, horizon, direction,
               confidence, emitted_at, calibrated
        FROM forecast_calibration
        WHERE resolved_at IS NULL
        ORDER BY emitted_at ASC
        """
    ).fetchall()

    now = datetime.now(tz=UTC)
    pending: list[CalibrationRecord] = []

    for row in rows:
        emitted_dt = _parse_iso_utc(str(row[7]))
        if emitted_dt is None:
            continue

        horizon = str(row[4])
        horizon_minutes = HORIZON_MINUTES.get(horizon)
        if horizon_minutes is None:
            continue

        age_minutes = (now - emitted_dt).total_seconds() / 60.0
        if age_minutes < float(horizon_minutes):
            continue
        if age_minutes > float(max_age_minutes):
            continue

        pending.append(
            CalibrationRecord(
                forecast_id=str(row[0]),
                producer_name=str(row[1]),
                asset=str(row[2]),
                regime=str(row[3]),
                horizon=horizon,
                direction=str(row[5]),
                confidence=float(row[6]),
                emitted_at=str(row[7]),
                calibrated=bool(int(row[8] or 0)),
            )
        )

        if len(pending) >= 100:
            break

    return pending


def brier_summary(db: Any, producer_name: str, window_days: int = 30) -> dict[str, Any]:
    """
    Return summary statistics for a producer's Brier scores over the last N days.
    Returns: {producer_name, window_days, count, mean_brier, mean_confidence,
              resolution_rate, regime_breakdown}
    """
    conn = _connection(db)
    rows = conn.execute(
        """
        SELECT regime, COUNT(*), AVG(brier_score), AVG(confidence)
        FROM forecast_calibration
        WHERE producer_name = ?
          AND resolved_at IS NOT NULL
          AND datetime(resolved_at) >= datetime('now', ? || ' days')
        GROUP BY regime
        """,
        (producer_name, f"-{window_days}"),
    ).fetchall()

    regime_breakdown: dict[str, dict[str, Any]] = {}
    total_count = 0
    brier_numerator = 0.0
    confidence_numerator = 0.0

    for row in rows:
        regime = str(row[0])
        count = int(row[1])
        mean_brier = float(row[2] or 0.0)
        mean_conf = float(row[3] or 0.0)

        regime_breakdown[regime] = {
            "count": count,
            "mean_brier": round(mean_brier, 4),
            "mean_confidence": round(mean_conf, 4),
        }

        total_count += count
        brier_numerator += mean_brier * count
        confidence_numerator += mean_conf * count

    # resolution rate
    unresolved = int(
        conn.execute(
            "SELECT COUNT(*) FROM forecast_calibration WHERE producer_name = ? AND resolved_at IS NULL",
            (producer_name,),
        ).fetchone()[0]
    )

    total_ever = int(
        conn.execute(
            "SELECT COUNT(*) FROM forecast_calibration WHERE producer_name = ?",
            (producer_name,),
        ).fetchone()[0]
    )

    resolution_rate = (total_ever - unresolved) / max(total_ever, 1)
    mean_brier_val = brier_numerator / total_count if total_count else 0.0
    mean_conf_val = confidence_numerator / total_count if total_count else 0.0

    return {
        "producer_name": producer_name,
        "window_days": window_days,
        "count": total_count,
        "mean_brier": round(mean_brier_val, 4),
        "mean_confidence": round(mean_conf_val, 4),
        "resolution_rate": round(resolution_rate, 3),
        "regime_breakdown": regime_breakdown,
    }
