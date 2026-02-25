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
from datetime import UTC, datetime

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

    def record_intent(self, *, trade_id: str, realized_pnl_usd: float) -> KarmaIntent | None:
        """Record a signed intent for a profitable trade.

        Returns intent if recorded, else None.
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

            with self._db.conn:
                self._db.conn.execute(
                    """
                    INSERT INTO karma_intents (
                        id, trade_id, realized_pnl_usd, karma_percentage, karma_amount_usd,
                        node_id, signature, settled, batch_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL, datetime('now'))
                    """,
                    (
                        intent_id,
                        str(trade_id),
                        pnl,
                        pct,
                        amount,
                        self._identity.node_id,
                        sig_b64,
                    ),
                )

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
                },
                dedupe_key=f"karma.intent:{intent_id}",
                source="karma",
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

    def get_pending_intents(self) -> list[KarmaIntent]:
        rows = self._db.conn.execute(
            """
            SELECT id, trade_id, realized_pnl_usd, karma_percentage, karma_amount_usd,
                   node_id, signature, created_at
            FROM karma_intents
            WHERE settled = 0
            ORDER BY created_at ASC
            """
        ).fetchall()
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
            rows = self._db.conn.execute(
                f"""
                SELECT id, karma_amount_usd
                FROM karma_intents
                WHERE id IN ({q_marks}) AND settled = 0
                """,
                tuple(intent_ids),
            ).fetchall()

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

            with self._db.conn:
                self._db.conn.execute(
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
                self._db.conn.execute(
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
        rows = self._db.conn.execute(
            """
            SELECT id, intent_ids, total_usd, destination_wallet, tx_hash, status, signature, created_at
            FROM karma_settlements
            ORDER BY created_at DESC
            """
        ).fetchall()

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
