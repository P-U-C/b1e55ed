"""Learnable scoring functions.

Replaces hardcoded heuristics in producers with parameterized equivalents.
Parameters are stored in ``scoring_params``.

Shadow mode (default): ``value_live = value_default``. The learning loop can
update ``value_shadow`` from outcomes, but must not update ``value_live`` until
an operator explicitly promotes a parameter.

This is the P2 entry point for learnable scoring. P4 can build on this module
for outcome-driven calibration proposals.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)


# Default parameters for known scoring functions.
# These values mirror the current hardcoded scoring behavior.
DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "tradfi.funding_optimal_center": {
        "producer_name": "tradfi_basis",
        "param_type": "optimal_center",
        "value_default": 10.0,
        "notes": "Optimal annualized funding rate (%). Hardcoded was 10.0.",
    },
    "tradfi.funding_scale": {
        "producer_name": "tradfi_basis",
        "param_type": "scale",
        "value_default": 30.0,
        "notes": "Funding deviation scale factor. Hardcoded was 30.0.",
    },
    "tradfi.basis_optimal_center": {
        "producer_name": "tradfi_basis",
        "param_type": "optimal_center",
        "value_default": 5.0,
        "notes": "Optimal annualized basis (%). Hardcoded was 5.0.",
    },
    "tradfi.basis_scale": {
        "producer_name": "tradfi_basis",
        "param_type": "scale",
        "value_default": 15.0,
        "notes": "Basis deviation scale factor. Hardcoded was 15.0.",
    },
}


def _resolve_conn(db: Any) -> sqlite3.Connection:
    """Resolve a sqlite connection from Database or sqlite3.Connection input."""
    if isinstance(db, sqlite3.Connection):
        return db
    conn = getattr(db, "conn", None)
    if isinstance(conn, sqlite3.Connection):
        return conn
    raise TypeError("Expected sqlite3.Connection or engine.core.database.Database")


def ensure_defaults(db: Any) -> None:
    """Ensure all DEFAULT_PARAMS rows exist in scoring_params.

    Idempotent: safe to call repeatedly (e.g., startup).
    """
    conn = _resolve_conn(db)
    with conn:
        for key, meta in DEFAULT_PARAMS.items():
            conn.execute(
                """
                INSERT OR IGNORE INTO scoring_params
                    (param_key, producer_name, param_type,
                     value_default, value_shadow, value_live,
                     shadow_mode, notes)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    key,
                    str(meta["producer_name"]),
                    str(meta["param_type"]),
                    float(meta["value_default"]),
                    float(meta["value_default"]),
                    float(meta["value_default"]),
                    str(meta.get("notes", "")),
                ),
            )


def get_param(db: Any, param_key: str) -> float:
    """Return a parameter's live value.

    In shadow mode, this returns ``value_default`` to preserve the invariant
    that live scoring remains default until explicitly promoted.

    If the row is missing, falls back to ``DEFAULT_PARAMS``.
    """
    conn = _resolve_conn(db)
    row = conn.execute(
        "SELECT value_default, value_live, shadow_mode FROM scoring_params WHERE param_key = ?",
        (param_key,),
    ).fetchone()
    if row is not None:
        value_default = float(row[0])
        value_live = float(row[1])
        shadow_mode = bool(row[2])
        if shadow_mode:
            return value_default
        return value_live
    return float(DEFAULT_PARAMS.get(param_key, {}).get("value_default", 0.0))


def propose_shadow_update(db: Any, param_key: str, new_value: float, reason: str = "") -> bool:
    """Update ``value_shadow`` without affecting ``value_live``.

    Returns ``True`` when the row exists, else ``False``.
    """
    conn = _resolve_conn(db)
    row = conn.execute(
        "SELECT id FROM scoring_params WHERE param_key = ?",
        (param_key,),
    ).fetchone()
    if row is None:
        logger.warning("propose_shadow_update: unknown param_key %s", param_key)
        return False
    with conn:
        conn.execute(
            """
            UPDATE scoring_params
            SET value_shadow = ?,
                last_updated = datetime('now'),
                notes = CASE WHEN ? != '' THEN ? ELSE notes END
            WHERE param_key = ?
            """,
            (float(new_value), reason, reason, param_key),
        )
    return True


def promote_to_live(db: Any, param_key: str) -> bool:
    """Promote ``value_shadow`` to ``value_live`` and disable shadow mode."""
    conn = _resolve_conn(db)
    row = conn.execute(
        "SELECT value_shadow FROM scoring_params WHERE param_key = ?",
        (param_key,),
    ).fetchone()
    if row is None:
        return False
    new_live = float(row[0])
    with conn:
        conn.execute(
            """
            UPDATE scoring_params
            SET value_live = value_shadow,
                shadow_mode = 0,
                last_updated = datetime('now')
            WHERE param_key = ?
            """,
            (param_key,),
        )
    logger.info("Promoted scoring param %s to live (value=%.3f)", param_key, new_live)
    return True


def list_params(db: Any, producer_name: str | None = None) -> list[dict[str, Any]]:
    """Return all scoring params, optionally filtered by producer."""
    conn = _resolve_conn(db)
    query = "SELECT param_key, producer_name, param_type, value_default, value_shadow, value_live, shadow_mode, last_updated, notes FROM scoring_params"
    args: tuple[Any, ...] = ()
    if producer_name:
        query += " WHERE producer_name = ?"
        args = (producer_name,)
    rows = conn.execute(query, args).fetchall()
    return [
        {
            "param_key": row[0],
            "producer_name": row[1],
            "param_type": row[2],
            "value_default": row[3],
            "value_shadow": row[4],
            "value_live": row[5],
            "shadow_mode": bool(row[6]),
            "last_updated": row[7],
            "notes": row[8],
        }
        for row in rows
    ]
