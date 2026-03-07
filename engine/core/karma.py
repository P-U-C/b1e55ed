"""engine.core.karma

Volume-dampened karma + LLM karma ceiling (DeerFlow S0).

Information-theoretic frequency penalty: high-frequency producers
earn less karma per signal. Prevents gaming by signal spam.

LLM karma ceiling: AI-sourced signals start with a karma cap of 0.3,
which rises by 0.1 per validated outcome. Trust is earned, not assumed.
"""

from __future__ import annotations

import logging

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from datetime import datetime

from engine.core.database import Database

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_LLM_KARMA_CEILING = 0.3
_CEILING_INCREMENT = 0.1
_MAX_CEILING = 1.0


# ---------------------------------------------------------------------------
# Frequency penalty
# ---------------------------------------------------------------------------


# Shannon (1948): a source that repeats itself carries less information.
# The frequency penalty is source coding for karma.
# A producer saying the same thing 50 times per day is not 50x more informative.
def frequency_penalty(signals_per_day: float) -> float:
    """Returns a multiplier [0.1, 1.0] applied to karma earned per signal.

    High-frequency producers earn less karma per signal (information theory).
    Penalty is per (producer, symbol) pair — not per producer globally.
    """
    if signals_per_day <= 1:
        return 1.0
    elif signals_per_day <= 5:
        return 0.7
    elif signals_per_day <= 20:
        return 0.4
    else:
        return 0.1


def _compute_daily_rate(db: Database, producer_name: str, symbol: str) -> float:
    """Compute signals-per-day for a (producer, symbol) pair over the last 7 days."""
    row = db.conn.execute(
        """
        SELECT COUNT(*) * 1.0 / MAX(1, (julianday('now') - julianday(MIN(ts))))
        FROM events
        WHERE source = ? AND ts > datetime('now', '-7 days')
        AND json_extract(payload, '$.symbol') = ?
        """,
        (producer_name, symbol),
    ).fetchone()
    if row is None or row[0] is None:
        return 0.0
    return float(row[0])


def karma_weight_for_signal(db: Database, producer_name: str, symbol: str) -> float:
    """Compute the karma weight multiplier for a signal from (producer, symbol).

    Combines:
    1. Frequency penalty (volume dampening)
    2. LLM karma ceiling (if applicable)

    Returns a float in [0.0, 1.0] that should multiply the raw karma earned.
    """
    daily_rate = _compute_daily_rate(db, producer_name, symbol)
    freq_mult = frequency_penalty(daily_rate)

    # Check LLM ceiling
    ceiling_mult = 1.0
    row = db.conn.execute(
        "SELECT karma_ceiling FROM producer_karma_config WHERE producer_name = ?",
        (producer_name,),
    ).fetchone()
    if row is not None:
        ceiling_mult = min(float(row[0]), _MAX_CEILING)

    return freq_mult * ceiling_mult


# ---------------------------------------------------------------------------
# LLM ceiling management
# ---------------------------------------------------------------------------


# The academic tenure track, compressed to a float.
# New faculty start probationary (0.3). Each validated paper raises the ceiling.
# Full tenure at 1.0. The department votes with outcomes, not credentials.
def ensure_producer_karma_config(db: Database, producer_name: str, source_type: str = "unknown") -> None:
    """Ensure a producer_karma_config row exists for the given producer.

    Creates with default LLM ceiling if source_type starts with 'llm_' or 'deerflow:'.
    """
    is_llm = source_type.startswith("llm_") or source_type.startswith("deerflow:")
    default_ceiling = _DEFAULT_LLM_KARMA_CEILING if is_llm else _MAX_CEILING
    now_iso = datetime.now(tz=UTC).isoformat()

    db.conn.execute(
        """
        INSERT INTO producer_karma_config (producer_name, karma_ceiling, source_type, ceiling_validated_count, updated_at)
        VALUES (?, ?, ?, 0, ?)
        ON CONFLICT(producer_name) DO NOTHING
        """,
        (producer_name, default_ceiling, source_type, now_iso),
    )


def bump_karma_ceiling(db: Database, producer_name: str) -> float:
    """Increment karma ceiling by 0.1 after a validated outcome.

    Returns the new ceiling value.
    """
    now_iso = datetime.now(tz=UTC).isoformat()
    db.conn.execute(
        """
        UPDATE producer_karma_config
        SET karma_ceiling = MIN(?, karma_ceiling + ?),
            ceiling_validated_count = ceiling_validated_count + 1,
            updated_at = ?
        WHERE producer_name = ?
        """,
        (_MAX_CEILING, _CEILING_INCREMENT, now_iso, producer_name),
    )
    row = db.conn.execute(
        "SELECT karma_ceiling FROM producer_karma_config WHERE producer_name = ?",
        (producer_name,),
    ).fetchone()
    return float(row[0]) if row else _MAX_CEILING
