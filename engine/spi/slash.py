"""Slash conditions for SPI producers."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from engine.spi.lifecycle import transition

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Slash condition checks
# ---------------------------------------------------------------------------


def _check_karma_floor(db, producer_id: str) -> dict | None:  # noqa: ANN001
    """Check if running_karma < 0.30 for 3+ consecutive epochs."""
    rows = db.fetchall(
        """
        SELECT running_karma FROM spi_karma
        WHERE producer_id = ?
        ORDER BY epoch DESC LIMIT 3
        """,
        (producer_id,),
    )
    if len(rows) < 3:
        return None

    values = [r[0] for r in rows]
    if all(v < 0.30 for v in values):
        return {
            "condition": "karma_floor",
            "severity": "suspend",
            "detail": (f"running_karma below 0.30 for 3 consecutive epochs: {[round(v, 4) for v in values]}"),
        }
    return None


def _check_signal_spam(db, producer_id: str) -> dict | None:  # noqa: ANN001
    """Check if >100 signals submitted in the last 1 hour."""
    one_hour_ago = (datetime.now(tz=UTC) - timedelta(hours=1)).isoformat()
    row = db.fetchone(
        """
        SELECT COUNT(*) FROM spi_signals
        WHERE producer_id = ?
          AND submitted_at >= ?
        """,
        (producer_id, one_hour_ago),
    )
    count = row[0] if row else 0
    if count > 100:
        return {
            "condition": "signal_spam",
            "severity": "warn",
            "detail": f"{count} signals submitted in the last hour (threshold: 100)",
        }
    return None


def _check_zero_resolution(db, producer_id: str) -> dict | None:  # noqa: ANN001
    """Check if 0 resolved signals after 7 days active."""
    # Find when the producer first became active
    producer_row = db.fetchone(
        "SELECT lifecycle_state, registered_at FROM spi_producers WHERE producer_id = ?",
        (producer_id,),
    )
    if producer_row is None:
        return None

    lifecycle_state, registered_at = producer_row[0], producer_row[1]
    if lifecycle_state != "active":
        return None

    # Use registered_at as a proxy for when they went active
    # (good enough for the slash check; precise tracking deferred to v1.1+)
    try:
        registered_dt = datetime.fromisoformat(registered_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None

    days_active = (datetime.now(tz=UTC) - registered_dt).total_seconds() / 86400
    if days_active < 7:
        return None

    row = db.fetchone(
        "SELECT COUNT(*) FROM spi_signals WHERE producer_id = ? AND status = 'resolved'",
        (producer_id,),
    )
    resolved_count = row[0] if row else 0
    if resolved_count == 0:
        return {
            "condition": "zero_resolution",
            "severity": "warn",
            "detail": (f"0 resolved signals after {days_active:.1f} days active (threshold: 7 days)"),
        }
    return None


# Slash condition registry: (name, check_fn, severity)
SLASH_CONDITIONS = [
    ("karma_floor", _check_karma_floor, "suspend"),
    ("signal_spam", _check_signal_spam, "warn"),
    ("zero_resolution", _check_zero_resolution, "warn"),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_slash_conditions(db, producer_id: str) -> list[dict]:  # noqa: ANN001
    """Return list of triggered slash conditions.

    Each entry: {condition: str, severity: str, detail: str}
    """
    triggered: list[dict] = []
    for _name, check_fn, _severity in SLASH_CONDITIONS:
        try:
            result = check_fn(db, producer_id)
            if result is not None:
                triggered.append(result)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "spi.slash.check_error condition=%s producer=%s error=%s",
                _name,
                producer_id,
                exc,
            )
    return triggered


def apply_slash(db, producer_id: str, condition: str, severity: str) -> dict:  # noqa: ANN001
    """Apply a slash action.

    - warn  → logs only, no state change
    - suspend → transitions producer to 'suspended'

    Returns: {producer_id, condition, severity, action, state_changed}
    """
    if severity == "warn":
        logger.warning(
            "spi.slash.warn producer=%s condition=%s",
            producer_id,
            condition,
        )
        return {
            "producer_id": producer_id,
            "condition": condition,
            "severity": severity,
            "action": "logged",
            "state_changed": False,
        }

    if severity == "suspend":
        try:
            transition(db, producer_id, "suspended")
            logger.warning(
                "spi.slash.suspend producer=%s condition=%s",
                producer_id,
                condition,
            )
            return {
                "producer_id": producer_id,
                "condition": condition,
                "severity": severity,
                "action": "suspended",
                "state_changed": True,
            }
        except ValueError as exc:
            logger.warning(
                "spi.slash.suspend_failed producer=%s condition=%s error=%s",
                producer_id,
                condition,
                exc,
            )
            return {
                "producer_id": producer_id,
                "condition": condition,
                "severity": severity,
                "action": "suspend_failed",
                "state_changed": False,
                "error": str(exc),
            }

    # Unknown severity — log and no-op
    logger.error(
        "spi.slash.unknown_severity producer=%s condition=%s severity=%s",
        producer_id,
        condition,
        severity,
    )
    return {
        "producer_id": producer_id,
        "condition": condition,
        "severity": severity,
        "action": "noop_unknown_severity",
        "state_changed": False,
    }
