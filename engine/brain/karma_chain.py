"""engine.brain.karma_chain

KarmaChainWriter — batches karma feedback events and writes them to the
ERC-8004 Reputation Registry after each resolved forecast.

Fail-open: if chain_client is None, all methods are no-ops.
Events are persisted to karma_chain_queue so they survive restarts.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    UTC = UTC  # type: ignore[assignment]

if TYPE_CHECKING:
    from engine.core.database import Database
    from engine.oracle.chain import ChainClient

logger = logging.getLogger("b1e55ed.karma_chain")

_ORACLE_BASE = "https://oracle.b1e55ed.permanentupperclass.com/api/v1/outcomes"


class KarmaChainWriter:
    """Batches karma feedback events and writes them to the on-chain Reputation Registry."""

    def __init__(
        self,
        chain_client: ChainClient | None,
        db: Database,
        batch_size: int = 10,
    ) -> None:
        self._chain_client = chain_client
        self._db = db
        self._batch_size = batch_size
        self._pending: list[dict] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def queue_karma_event(
        self,
        agent_id: int,
        karma_delta: float,
        forecast_id: str,
        producer_node_id: str,
    ) -> None:
        """Queue a karma event for batch write. Non-blocking.

        Persists to DB immediately so events survive restarts, then adds
        to in-memory pending list for flush().
        """
        if self._chain_client is None:
            logger.debug("queue_karma_event: chain_client is None — no-op")
            return

        outcome_json = self._build_outcome_json(
            {
                "agent_id": agent_id,
                "karma_delta": karma_delta,
                "forecast_id": forecast_id,
                "producer_node_id": producer_node_id,
            }
        )

        try:
            self._db.execute(
                """
                INSERT INTO karma_chain_queue
                    (agent_id, karma_delta, forecast_id, producer_node_id, outcome_json, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
                """,
                (agent_id, karma_delta, forecast_id, producer_node_id, outcome_json),
            )
            self._db.conn.commit()
        except Exception:
            logger.warning("queue_karma_event: failed to persist to DB", exc_info=True)
            return

        self._pending.append(
            {
                "agent_id": agent_id,
                "karma_delta": karma_delta,
                "forecast_id": forecast_id,
                "producer_node_id": producer_node_id,
                "outcome_json": outcome_json,
            }
        )

    def flush(self) -> list[str]:
        """Flush queued events to chain. Returns list of tx_hashes.

        Loads any un-submitted DB rows (covers events from prior restarts),
        then submits up to batch_size at a time.
        """
        if self._chain_client is None:
            self._pending.clear()
            return []

        # Merge DB pending rows with in-memory pending (dedupe by forecast_id)
        db_pending = self._load_pending_from_db()
        seen: set[str] = set()
        merged: list[dict] = []
        for evt in [*db_pending, *self._pending]:
            fid = str(evt["forecast_id"])
            if fid not in seen:
                seen.add(fid)
                merged.append(evt)

        self._pending.clear()

        if not merged:
            return []

        tx_hashes: list[str] = []
        batch = merged[: self._batch_size]

        for event in batch:
            try:
                outcome_json = event.get("outcome_json") or self._build_outcome_json(event)
                file_hash = hashlib.sha3_256(outcome_json.encode()).digest()[:32]
                file_uri = f"{_ORACLE_BASE}/{event['forecast_id']}"

                tx_hash = self._chain_client.post_karma_feedback(
                    agent_id=int(event["agent_id"]),
                    karma_delta=float(event["karma_delta"]),
                    tag="karma",
                    file_uri=file_uri,
                    file_hash=file_hash,
                )

                if tx_hash:
                    tx_hashes.append(tx_hash)
                    self._mark_submitted(str(event["forecast_id"]), tx_hash)
                    logger.info(
                        "karma_chain_flush: submitted agent_id=%s karma=%.4f tx=%s",
                        event["agent_id"],
                        event["karma_delta"],
                        tx_hash,
                    )
                else:
                    self._mark_failed(str(event["forecast_id"]))
            except Exception:
                logger.warning(
                    "karma_chain_flush: failed for forecast_id=%s",
                    event.get("forecast_id"),
                    exc_info=True,
                )
                self._mark_failed(str(event.get("forecast_id", "")))

        return tx_hashes

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_outcome_json(self, event: dict) -> str:
        """Build the outcome JSON that gets stored as fileURI payload."""
        payload = {
            "version": "1.0",
            "type": "karma_outcome",
            "agent_id": event.get("agent_id"),
            "karma_delta": event.get("karma_delta"),
            "forecast_id": event.get("forecast_id"),
            "producer_node_id": event.get("producer_node_id"),
            "timestamp": datetime.now(tz=UTC).isoformat(),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def _load_pending_from_db(self) -> list[dict]:
        """Load un-submitted events from karma_chain_queue."""
        try:
            rows = self._db.execute(
                """
                SELECT agent_id, karma_delta, forecast_id, producer_node_id, outcome_json
                FROM karma_chain_queue
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (self._batch_size,),
            ).fetchall()
            return [
                {
                    "agent_id": row["agent_id"],
                    "karma_delta": row["karma_delta"],
                    "forecast_id": row["forecast_id"],
                    "producer_node_id": row["producer_node_id"],
                    "outcome_json": row["outcome_json"],
                }
                for row in rows
            ]
        except Exception:
            logger.warning("_load_pending_from_db: failed", exc_info=True)
            return []

    def _mark_submitted(self, forecast_id: str, tx_hash: str) -> None:
        try:
            self._db.execute(
                """
                UPDATE karma_chain_queue
                SET status = 'submitted', tx_hash = ?, submitted_at = datetime('now')
                WHERE forecast_id = ? AND status = 'pending'
                """,
                (tx_hash, forecast_id),
            )
            self._db.conn.commit()
        except Exception:
            logger.warning("_mark_submitted: failed for forecast_id=%s", forecast_id, exc_info=True)

    def _mark_failed(self, forecast_id: str) -> None:
        try:
            self._db.execute(
                """
                UPDATE karma_chain_queue
                SET status = 'failed'
                WHERE forecast_id = ? AND status = 'pending'
                """,
                (forecast_id,),
            )
            self._db.conn.commit()
        except Exception:
            logger.warning("_mark_failed: failed for forecast_id=%s", forecast_id, exc_info=True)
