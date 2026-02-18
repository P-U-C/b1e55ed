"""engine.security.audit

Database-backed audit logger.

The goal is not theatrics — it's forensic usability.
The chain remembers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from engine.core.database import Database


def _dt_to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


@dataclass
class AuditLogger:
    """Writes security-relevant actions to the `audit_log` table."""

    db: Database
    component: str = "security"

    def log_action(self, action: str, actor: str | None, details: dict[str, Any] | None = None) -> None:
        payload = json.dumps(details or {}, sort_keys=True)
        with self.db.conn:
            self.db.conn.execute(
                "INSERT INTO audit_log (action, actor, component, details) VALUES (?, ?, ?, ?)",
                (action, actor, self.component, payload),
            )

    def query(
        self,
        action_type: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        q = "SELECT ts, action, actor, component, details FROM audit_log WHERE 1=1"
        params: list[Any] = []

        if action_type is not None:
            q += " AND action = ?"
            params.append(action_type)

        if since is not None:
            q += " AND ts >= ?"
            params.append(_dt_to_iso(since))

        q += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)

        rows = self.db.conn.execute(q, tuple(params)).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "ts": r[0],
                    "action": r[1],
                    "actor": r[2],
                    "component": r[3],
                    "details": json.loads(r[4]) if r[4] else {},
                }
            )
        return out
