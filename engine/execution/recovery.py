"""engine.execution.recovery

Crash-recovery helpers for execution state.

On an ungraceful shutdown (OOM kill, power loss, etc.) a position can close
without its karma intent being recorded.  This module provides a startup sweep
that finds such positions and records the missing intents idempotently.

The idempotency guarantee comes from INSERT OR IGNORE in karma.record_intent():
a second call for the same trade_id is silently a no-op.
"""

from __future__ import annotations

import logging

from engine.core.config import Config
from engine.core.database import Database
from engine.security.identity import NodeIdentity

_log = logging.getLogger("b1e55ed.execution.recovery")


def recover_missing_karma_intents(
    db: Database,
    config: Config,
    identity: NodeIdentity,
) -> int:
    """Find closed positions with no karma intent and record them.

    Idempotent: safe to call on every startup.

    Returns the count of intents successfully recovered.
    """
    from engine.execution.karma import KarmaEngine

    try:
        rows = db.fetchall(
            """
            SELECT p.id, p.realized_pnl
            FROM positions p
            LEFT JOIN karma_intents ki ON ki.trade_id = p.id
            WHERE p.status = 'closed'
              AND p.realized_pnl IS NOT NULL
              AND ki.id IS NULL
            """
        )
    except Exception:
        _log.warning("recover_missing_karma_intents: failed to query positions", exc_info=True)
        return 0

    if not rows:
        return 0

    karma = KarmaEngine(config=config, db=db, identity=identity)
    recovered = 0

    for row in rows:
        try:
            result = karma.record_intent(
                trade_id=str(row["id"]),
                realized_pnl_usd=float(row["realized_pnl"]),
            )
            if result is not None:
                recovered += 1
        except Exception:
            _log.warning(
                "recover_missing_karma_intents: failed for position %s",
                row["id"],
                exc_info=True,
            )

    if recovered > 0:
        _log.info("recover_missing_karma_intents: recovered %d karma intents", recovered)

    return recovered
