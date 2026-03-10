"""engine.execution.karma

Karma v2.0 (PRD v3 §18)

This mechanism is simple on purpose.

- Realized profit only. Never losses.
- Default-on, operator-controlled.
- Two-phase flow:
  A) Intent (local, automatic): record what *would* be contributed.
  B) Settlement (explicit): operator chooses when to actually pay.
- Non-blocking: karma failure must never break execution.

The point is not moral accounting. It is infrastructure funding.
A compounding commons is a defensible advantage: shared inputs improve the engine,
which improves outcomes, which funds better shared inputs.

Tone constraint: builders, conviction, pride. No shame language.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017


from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType, canonical_json
from engine.security.identity import NodeIdentity


@dataclass(frozen=True)
class KarmaIntent:
    id: str
    trade_id: str
    realized_pnl_usd: float
    karma_percentage: float
    karma_amount_usd: float
    node_id: str
    signature_b64: str
    created_at: str


@dataclass(frozen=True)
class KarmaReceipt:
    id: str
    intent_ids: list[str]
    total_usd: float
    destination_wallet: str
    tx_hash: str | None
    status: str
    signature_b64: str
    created_at: str


def _utc_now_iso(now_fn: Callable[[], datetime] | None = None) -> str:
    n = (now_fn or (lambda: datetime.now(tz=UTC)))()
    if n.tzinfo is None:
        n = n.replace(tzinfo=UTC)
    return n.astimezone(UTC).isoformat()


def _sign_payload(identity: NodeIdentity, payload: dict) -> str:
    """Return base64 signature for canonical-json payload."""

    data = canonical_json(payload).encode("utf-8")
    sig = identity.sign(data)
    import base64

    return base64.b64encode(sig).decode("ascii")


class KarmaEngine:
    """Records karma intents on profitable trade close; batches settlements.

    Fail-open contract:
    - record_intent() never raises
    - settle() never raises

    The operator controls when a settlement occurs.
    """

    def __init__(
        self,
        *,
        config: Config,
        db: Database,
        identity: NodeIdentity,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._db = db
        self._identity = identity
        self._now_fn = now_fn

    @property
    def enabled(self) -> bool:
        return bool(self._config.karma.enabled) and float(self._config.karma.percentage) > 0.0

    def record_intent(
        self,
        *,
        trade_id: str,
        realized_pnl_usd: float,
        contributor_id: str | None = None,
    ) -> KarmaIntent | None:
        """Record a signed intent for a profitable trade.

        Uses INSERT OR IGNORE so duplicate trade_ids are silently skipped (safe for
        retries and crash-recovery sweeps).  Returns None if the row already exists.

        Returns intent if recorded, else None.

        The idempotency key (trade_id UNIQUE) applies the same structural
        constraint Satoshi introduced in 2008: with concurrent writers and a
        shared ledger, the first write wins and retries are silent. The problem
        was not cryptographic. It was about ordering.
        """

        try:
            if not self.enabled:
                return None
            if not self._config.karma.treasury_address:
                # PRD: intent recording is gated on treasury configuration.
                return None
            pnl = float(realized_pnl_usd)
            if pnl <= 0.0:
                return None

            pct = float(self._config.karma.percentage)
            amount = pnl * pct

            intent_id = str(uuid.uuid4())
            created_at = _utc_now_iso(self._now_fn)

            payload = {
                "id": intent_id,
                "trade_id": str(trade_id),
                "realized_pnl_usd": pnl,
                "karma_percentage": pct,
                "karma_amount_usd": amount,
                "node_id": self._identity.node_id,
                "created_at": created_at,
            }
            sig_b64 = _sign_payload(self._identity, payload)

            with self._db._lock, self._db.conn:
                cursor = self._db.execute(
                    """
                    INSERT OR IGNORE INTO karma_intents (
                        id, trade_id, contributor_id, realized_pnl_usd, karma_percentage,
                        karma_amount_usd, node_id, signature, settled, batch_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, datetime('now'))
                    """,
                    (
                        intent_id,
                        str(trade_id),
                        contributor_id,
                        pnl,
                        pct,
                        amount,
                        self._identity.node_id,
                        sig_b64,
                    ),
                )

            # If the row was not inserted (duplicate trade_id), return None.
            if cursor.rowcount == 0:
                return None

            # Emit an event as well (append-only memory)
            self._db.append_event(
                event_type=EventType.KARMA_INTENT_V1,
                payload={
                    "trade_id": str(trade_id),
                    "realized_pnl_usd": pnl,
                    "karma_percentage": pct,
                    "karma_amount_usd": amount,
                    "node_id": self._identity.node_id,
                    "signature_b64": sig_b64,
                    "intent_id": intent_id,
                    "contributor_id": contributor_id,
                },
                dedupe_key=f"karma.intent:{intent_id}",
                source="karma",
                contributor_id=contributor_id,
            )

            return KarmaIntent(
                id=intent_id,
                trade_id=str(trade_id),
                realized_pnl_usd=pnl,
                karma_percentage=pct,
                karma_amount_usd=amount,
                node_id=self._identity.node_id,
                signature_b64=sig_b64,
                created_at=created_at,
            )
        except Exception:
            # Non-blocking guarantee: never break execution for karma.
            return None

    # ------------------------------------------------------------------
    # Flywheel attribution (S2): producer karma based on trade outcomes
    # ------------------------------------------------------------------

    def attribute_outcome(self, *, trade_id: str, realized_pnl_usd: float) -> dict:
        """Look up SIGNAL_ACCEPTED_V1 events for trade_id, update producer karma, emit ATTRIBUTION_OUTCOME_V1.

        Non-blocking contract: wraps entire body in try/except, logs errors, never raises.
        """
        import logging

        _log = logging.getLogger("b1e55ed.execution.karma")

        try:
            pnl = float(realized_pnl_usd)

            # 1. Query SIGNAL_ACCEPTED_V1 events for this trade
            rows = self._db.fetchall(
                "SELECT id, payload FROM events WHERE type = ? AND payload LIKE ?",
                (str(EventType.SIGNAL_ACCEPTED_V1), f'%"trade_id":"{trade_id}"%'),
            )

            # Also try alternate JSON formatting (spaces after colon)
            if not rows:
                rows = self._db.fetchall(
                    "SELECT id, payload FROM events WHERE type = ? AND payload LIKE ?",
                    (str(EventType.SIGNAL_ACCEPTED_V1), f'%"trade_id": "{trade_id}"%'),
                )

            if not rows:
                _log.warning("attribute_outcome: no SIGNAL_ACCEPTED_V1 events for trade_id=%s", trade_id)
                return {}

            # 2. Compute outcome
            if abs(pnl) < 0.01:
                outcome = 0.0
            elif pnl > 0:
                outcome = 1.0
            else:
                outcome = -1.0

            # 3. Determine confidence bucket for the event payload
            if abs(pnl) > 100:
                confidence_bucket = "high"
            elif abs(pnl) > 10:
                confidence_bucket = "mid"
            else:
                confidence_bucket = "low"

            producers: list[dict] = []
            now_iso = _utc_now_iso(self._now_fn)

            for row in rows:
                payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
                producer_id = str(payload.get("producer_id", "unknown"))
                domain = str(payload.get("domain", "unknown"))
                contribution_weight = float(payload.get("contribution_weight", 1.0))

                # 4. EMA update
                karma_delta = 0.0
                with self._db._lock, self._db.conn:
                    existing = self._db.fetchone(
                        "SELECT karma_score, win_count, loss_count, total_trades FROM producer_karma WHERE producer_id = ?",
                        (producer_id,),
                    )

                    if existing:
                        old_karma = float(existing[0])
                        win_count = int(existing[1])
                        loss_count = int(existing[2])
                        total_trades = int(existing[3])
                    else:
                        old_karma = 1.0
                        win_count = 0
                        loss_count = 0
                        total_trades = 0

                    total_trades += 1

                    if outcome > 0:
                        # Phase 0: positive outcomes update karma EMA
                        new_karma = old_karma * 0.95 + outcome * 0.05
                        karma_delta = new_karma - old_karma
                        win_count += 1
                    elif outcome < 0:
                        # Phase 0: losses tracked but NOT applied to karma_score
                        new_karma = old_karma
                        loss_count += 1
                    else:
                        new_karma = old_karma

                    self._db.execute(
                        """INSERT INTO producer_karma (producer_id, karma_score, win_count, loss_count, total_trades, last_updated)
                           VALUES (?, ?, ?, ?, ?, ?)
                           ON CONFLICT(producer_id) DO UPDATE SET
                             karma_score = excluded.karma_score,
                             win_count = excluded.win_count,
                             loss_count = excluded.loss_count,
                             total_trades = excluded.total_trades,
                             last_updated = excluded.last_updated""",
                        (producer_id, new_karma, win_count, loss_count, total_trades, now_iso),
                    )

                producers.append(
                    {
                        "producer_id": producer_id,
                        "domain": domain,
                        "contribution_weight": contribution_weight,
                        "outcome": outcome,
                        "karma_delta": karma_delta,
                    }
                )

            # 5. Emit ATTRIBUTION_OUTCOME_V1
            from engine.core.events import AttributionOutcomePayload, ProducerOutcome

            producer_outcomes = [
                ProducerOutcome(
                    producer_id=p["producer_id"],
                    domain=p["domain"],
                    contribution_weight=p["contribution_weight"],
                    outcome=p["outcome"],
                    karma_delta=p["karma_delta"],
                )
                for p in producers
            ]

            attribution_payload = AttributionOutcomePayload(
                trade_id=str(trade_id),
                realized_pnl_usd=pnl,
                confidence_bucket=confidence_bucket,
                producers=producer_outcomes,
            ).model_dump(mode="json")

            self._db.append_event(
                event_type=EventType.ATTRIBUTION_OUTCOME_V1,
                payload=attribution_payload,
                source="karma.attribution",
                dedupe_key=f"attribution.outcome:{trade_id}",
            )

            summary = {
                "trade_id": trade_id,
                "realized_pnl_usd": pnl,
                "outcome": outcome,
                "producers_updated": len(producers),
                "producers": producers,
            }
            _log.info("attribute_outcome complete: %s", summary)
            return summary

        except Exception:
            _log.warning("attribute_outcome failed for trade_id=%s", trade_id, exc_info=True)
            return {}

    def get_pending_intents(self, *, limit: int = 500, offset: int = 0) -> list[KarmaIntent]:
        rows = self._db.fetchall(
            """
            SELECT id, trade_id, realized_pnl_usd, karma_percentage, karma_amount_usd,
                   node_id, signature, created_at
            FROM karma_intents
            WHERE settled = 0
            ORDER BY created_at ASC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        out: list[KarmaIntent] = []
        for r in rows:
            out.append(
                KarmaIntent(
                    id=str(r[0]),
                    trade_id=str(r[1]),
                    realized_pnl_usd=float(r[2]),
                    karma_percentage=float(r[3]),
                    karma_amount_usd=float(r[4]),
                    node_id=str(r[5]),
                    signature_b64=str(r[6]) if r[6] is not None else "",
                    created_at=str(r[7]) if r[7] is not None else "",
                )
            )
        return out

    def settle(self, *, intent_ids: list[str], tx_hash: str | None = None) -> KarmaReceipt | None:
        """Batch-settle intents.

        This records a local receipt; it does not actually transfer funds.
        (On-chain settlement is a future adapter / operator action.)

        Returns a receipt if settlement recorded, else None.
        """

        try:
            if not intent_ids:
                return None
            if not self.enabled:
                return None
            if self._config.execution.mode != "live":
                # Paper PnL must never trigger real settlements.
                return None
            destination = str(self._config.karma.treasury_address)
            if not destination:
                return None

            # Load intents
            q_marks = ",".join(["?"] * len(intent_ids))
            rows = self._db.fetchall(
                f"""
                SELECT id, karma_amount_usd
                FROM karma_intents
                WHERE id IN ({q_marks}) AND settled = 0
                """,
                tuple(intent_ids),
            )

            if not rows:
                return None

            settled_ids = [str(r[0]) for r in rows]
            total = sum(float(r[1]) for r in rows)

            receipt_id = str(uuid.uuid4())
            created_at = _utc_now_iso(self._now_fn)
            status = "pending" if tx_hash is None else "submitted"

            receipt_payload = {
                "id": receipt_id,
                "intent_ids": settled_ids,
                "total_usd": total,
                "destination_wallet": destination,
                "tx_hash": tx_hash,
                "status": status,
                "node_id": self._identity.node_id,
                "created_at": created_at,
            }
            sig_b64 = _sign_payload(self._identity, receipt_payload)

            with self._db._lock, self._db.conn:
                self._db.execute(
                    """
                    INSERT INTO karma_settlements (
                        id, intent_ids, total_usd, destination_wallet, tx_hash, status, signature, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (
                        receipt_id,
                        json.dumps(settled_ids, sort_keys=True),
                        total,
                        destination,
                        tx_hash,
                        status,
                        sig_b64,
                    ),
                )
                self._db.execute(
                    f"""UPDATE karma_intents SET settled = 1, batch_id = ? WHERE id IN ({q_marks})""",
                    (receipt_id, *settled_ids),
                )

            self._db.append_event(
                event_type=EventType.KARMA_SETTLEMENT_V1,
                payload={
                    "receipt_id": receipt_id,
                    "intent_ids": settled_ids,
                    "total_usd": total,
                    "destination_wallet": destination,
                    "tx_hash": tx_hash,
                    "status": status,
                    "signature_b64": sig_b64,
                },
                dedupe_key=f"karma.settlement:{receipt_id}",
                source="karma",
            )
            self._db.append_event(
                event_type=EventType.KARMA_RECEIPT_V1,
                payload={
                    "receipt_id": receipt_id,
                    "intent_ids": settled_ids,
                    "total_usd": total,
                    "destination_wallet": destination,
                    "tx_hash": tx_hash,
                    "status": status,
                    "signature_b64": sig_b64,
                },
                dedupe_key=f"karma.receipt:{receipt_id}",
                source="karma",
            )

            return KarmaReceipt(
                id=receipt_id,
                intent_ids=settled_ids,
                total_usd=total,
                destination_wallet=destination,
                tx_hash=tx_hash,
                status=status,
                signature_b64=sig_b64,
                created_at=created_at,
            )
        except Exception:
            return None

    def get_receipts(self) -> list[KarmaReceipt]:
        rows = self._db.fetchall(
            """
            SELECT id, intent_ids, total_usd, destination_wallet, tx_hash, status, signature, created_at
            FROM karma_settlements
            ORDER BY created_at DESC
            """
        )

        out: list[KarmaReceipt] = []
        for r in rows:
            intent_ids = json.loads(str(r[1])) if r[1] is not None else []
            out.append(
                KarmaReceipt(
                    id=str(r[0]),
                    intent_ids=[str(x) for x in intent_ids],
                    total_usd=float(r[2]),
                    destination_wallet=str(r[3]),
                    tx_hash=str(r[4]) if r[4] is not None else None,
                    status=str(r[5]),
                    signature_b64=str(r[6]) if r[6] is not None else "",
                    created_at=str(r[7]) if r[7] is not None else "",
                )
            )
        return out
