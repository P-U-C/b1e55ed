"""SPI producer lifecycle state machine."""

from __future__ import annotations

import logging
from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State machine definition
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[str, set[str]] = {
    "onboarding": {"shadow"},
    "shadow": {"active", "suspended"},
    "active": {"suspended", "retired"},
    "suspended": {"active", "retired"},
    "retired": set(),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_producer(db, producer_id: str) -> dict | None:  # noqa: ANN001
    """Fetch producer row as dict. Returns None if not found."""
    row = db.fetchone(
        """
        SELECT producer_id, producer_name, lifecycle_state, ingress_mode,
               registered_at, created_at, updated_at
        FROM spi_producers
        WHERE producer_id = ?
        """,
        (producer_id,),
    )
    if row is None:
        return None
    keys = [
        "producer_id",
        "producer_name",
        "lifecycle_state",
        "ingress_mode",
        "registered_at",
        "created_at",
        "updated_at",
    ]
    return dict(zip(keys, row, strict=False))


def transition(db, producer_id: str, to_state: str) -> dict:  # noqa: ANN001
    """Transition producer to new lifecycle state.

    Raises ValueError on invalid transition or unknown producer.
    Returns the updated producer dict.
    """
    producer = get_producer(db, producer_id)
    if producer is None:
        raise ValueError(f"Producer '{producer_id}' not found")

    from_state = producer["lifecycle_state"]
    allowed = VALID_TRANSITIONS.get(from_state, set())

    if to_state not in allowed:
        raise ValueError(
            f"Invalid transition for producer '{producer_id}': {from_state!r} → {to_state!r}. Allowed from '{from_state}': {sorted(allowed) or '(none)'}"
        )

    now = datetime.now(tz=UTC).isoformat()
    db.execute(
        "UPDATE spi_producers SET lifecycle_state = ?, updated_at = ? WHERE producer_id = ?",
        (to_state, now, producer_id),
    )
    logger.info(
        "spi.lifecycle.transition producer=%s %s → %s",
        producer_id,
        from_state,
        to_state,
    )

    producer["lifecycle_state"] = to_state
    producer["updated_at"] = now
    return producer


# ---------------------------------------------------------------------------
# Promotion criteria
# ---------------------------------------------------------------------------


def check_promotion_criteria(db, producer_id: str) -> dict:  # noqa: ANN001
    """Check if producer meets criteria for onboarding→shadow or shadow→active promotion.

    onboarding→shadow: 5+ signals accepted (any status)
    shadow→active: 10+ resolved signals, running_karma >= 0.55

    Returns:
        {
            "eligible": bool,
            "reason": str,
            "current_state": str,
            "target_state": str,
        }
    """
    producer = get_producer(db, producer_id)
    if producer is None:
        return {
            "eligible": False,
            "reason": f"Producer '{producer_id}' not found",
            "current_state": "unknown",
            "target_state": "unknown",
        }

    current_state = producer["lifecycle_state"]

    if current_state == "onboarding":
        # Criteria: 5+ signals ever submitted
        row = db.fetchone(
            "SELECT COUNT(*) FROM spi_signals WHERE producer_id = ?",
            (producer_id,),
        )
        signal_count = row[0] if row else 0
        if signal_count >= 5:
            return {
                "eligible": True,
                "reason": f"Producer has {signal_count} accepted signals (threshold: 5)",
                "current_state": current_state,
                "target_state": "shadow",
            }
        return {
            "eligible": False,
            "reason": f"Producer has {signal_count}/5 required signals",
            "current_state": current_state,
            "target_state": "shadow",
        }

    if current_state == "shadow":
        # Criteria: 10+ resolved signals AND running_karma >= 0.55
        row = db.fetchone(
            "SELECT COUNT(*) FROM spi_signals WHERE producer_id = ? AND status = 'resolved'",
            (producer_id,),
        )
        resolved_count = row[0] if row else 0

        karma_row = db.fetchone(
            """
            SELECT running_karma FROM spi_karma
            WHERE producer_id = ?
            ORDER BY epoch DESC LIMIT 1
            """,
            (producer_id,),
        )
        running_karma = karma_row[0] if karma_row else 0.5

        if resolved_count >= 10 and running_karma >= 0.55:
            return {
                "eligible": True,
                "reason": (f"Producer has {resolved_count} resolved signals and running_karma={running_karma:.3f} (thresholds: 10, 0.55)"),
                "current_state": current_state,
                "target_state": "active",
            }

        reasons = []
        if resolved_count < 10:
            reasons.append(f"{resolved_count}/10 resolved signals")
        if running_karma < 0.55:
            reasons.append(f"karma={running_karma:.3f} < 0.55")
        return {
            "eligible": False,
            "reason": "Not eligible: " + ", ".join(reasons),
            "current_state": current_state,
            "target_state": "active",
        }

    # No promotion path from current state
    return {
        "eligible": False,
        "reason": f"No auto-promotion path from state '{current_state}'",
        "current_state": current_state,
        "target_state": "none",
    }


def maybe_auto_promote(db, producer_id: str) -> dict | None:  # noqa: ANN001
    """Auto-promote producer if criteria met.

    Returns the transition result dict if a promotion occurred, or None.
    """
    try:
        criteria = check_promotion_criteria(db, producer_id)
    except Exception:  # noqa: BLE001
        return None

    if not criteria.get("eligible"):
        return None

    target_state = criteria.get("target_state")
    if not target_state or target_state == "none":
        return None

    try:
        result = transition(db, producer_id, target_state)
        logger.info(
            "spi.lifecycle.auto_promote producer=%s promoted to %s",
            producer_id,
            target_state,
        )
        return result
    except ValueError:
        return None
