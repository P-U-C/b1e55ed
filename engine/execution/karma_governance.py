"""engine.execution.karma_governance

Settlement governance rules (K1):
1. Config immutability: percentage and treasury_address are locked after first settlement
2. Destination wallet changes require explicit migration event
3. Settlement audit trail separate from karma_settlements table

These are pre-settlement checks — call before KarmaEngine.settle().
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from engine.core.database import Database
from engine.core.events import EventType


@dataclass(frozen=True, slots=True)
class GovernanceCheckResult:
    allowed: bool
    reason: str = ""


class KarmaGovernance:
    """Enforces karma settlement governance rules."""

    def __init__(self, db: Database):
        self._db = db

    def has_prior_settlement(self) -> bool:
        """Check if any settlement has ever been recorded."""
        row = self._db.conn.execute("SELECT COUNT(1) FROM karma_settlements").fetchone()
        return bool(row and int(row[0]) > 0)

    def get_locked_config(self) -> dict | None:
        """Return the karma config from the first settlement, or None if no settlements exist.

        After first settlement, percentage and treasury_address are locked to these values.
        """
        row = self._db.conn.execute(
            "SELECT payload FROM events WHERE type = ? ORDER BY created_at ASC, rowid ASC LIMIT 1",
            (str(EventType.KARMA_SETTLEMENT_V1),),
        ).fetchone()
        if row is None:
            return None

        payload = json.loads(row[0])
        return {
            "destination_wallet": payload.get("destination_wallet", ""),
            "total_usd": payload.get("total_usd", 0),
        }

    def check_settlement_allowed(
        self,
        *,
        percentage: float,
        treasury_address: str,
    ) -> GovernanceCheckResult:
        """Validate that settlement config hasn't been changed opportunistically.

        Rules:
        - Before first settlement: any config is allowed
        - After first settlement: treasury_address must match the locked address
          (changes require explicit migration via KARMA_WALLET_MIGRATION event)
        """
        if not self.has_prior_settlement():
            return GovernanceCheckResult(allowed=True)

        # Check wallet hasn't changed without migration
        locked = self.get_locked_config()
        if locked is None:
            return GovernanceCheckResult(allowed=True)

        locked_wallet = locked.get("destination_wallet", "")
        if locked_wallet and treasury_address != locked_wallet:
            # Check if there's an approved migration
            if not self._has_wallet_migration(locked_wallet, treasury_address):
                return GovernanceCheckResult(
                    allowed=False,
                    reason=f"Treasury address changed from {locked_wallet} to {treasury_address} without migration event. Record a wallet migration first.",
                )

        return GovernanceCheckResult(allowed=True)

    def record_wallet_migration(
        self,
        *,
        old_wallet: str,
        new_wallet: str,
        reason: str,
        authorized_by: str,
    ) -> None:
        """Record an explicit wallet migration event."""
        self._db.append_event(
            event_type=EventType.KARMA_WALLET_MIGRATION_V1,
            payload={
                "old_wallet": old_wallet,
                "new_wallet": new_wallet,
                "reason": reason,
                "authorized_by": authorized_by,
            },
            source="karma.governance",
            dedupe_key=f"karma.migration:{old_wallet}->{new_wallet}",
        )

    def _has_wallet_migration(self, old_wallet: str, new_wallet: str) -> bool:
        """Check if an approved wallet migration exists."""
        rows = self._db.conn.execute(
            "SELECT payload FROM events WHERE type = ? ORDER BY created_at DESC",
            (str(EventType.KARMA_WALLET_MIGRATION_V1),),
        ).fetchall()

        for row in rows:
            payload = json.loads(row[0])
            if payload.get("old_wallet") == old_wallet and payload.get("new_wallet") == new_wallet:
                return True
        return False

    def get_settlement_audit_log(self, *, limit: int = 50) -> list[dict]:
        """Return settlement audit trail from events."""
        rows = self._db.conn.execute(
            """
            SELECT type, payload, ts, source FROM events
            WHERE type IN (?, ?, ?)
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (
                str(EventType.KARMA_SETTLEMENT_V1),
                str(EventType.KARMA_RECEIPT_V1),
                str(EventType.KARMA_WALLET_MIGRATION_V1),
                limit,
            ),
        ).fetchall()

        return [
            {
                "type": str(r[0]),
                "payload": json.loads(r[1]),
                "ts": str(r[2]),
                "source": str(r[3]) if r[3] else None,
            }
            for r in rows
        ]
