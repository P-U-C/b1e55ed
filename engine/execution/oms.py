"""engine.execution.oms

Order Management System (OMS).

Responsibilities (Sprint 2A):
- accept TradeIntent
- enforce preflight gates (policy, kill switch, etc.)
- size the position
- route to paper or live broker
- persist canonical state to DB via orders/positions tables and execution events

Modes:
- paper: implemented (PaperBroker)
- live: adapter boundary only (Sprint 2B)

No dry_run mode (DECISIONS_V3 #4).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from engine.brain.kill_switch import KillSwitchLevel
from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType, SignalAcceptedPayload
from engine.core.policy import TradingPolicyEngine
from engine.core.types import TradeIntent
from engine.execution.paper import PaperBroker
from engine.execution.position_sizer import CorrelationAwareSizer, PositionSizer, RiskLimits
from engine.execution.preflight import Preflight


@dataclass(frozen=True, slots=True)
class OMSResult:
    status: str  # filled|rejected|error
    mode: str
    order_id: str | None = None
    position_id: str | None = None
    notional_usd: float | None = None
    reasons: list[str] | None = None


class OMS:
    def __init__(
        self,
        *,
        config: Config,
        db: Database,
        preflight: Preflight,
        sizer: CorrelationAwareSizer,
        paper_broker: PaperBroker | None = None,
        policy: TradingPolicyEngine | None = None,
    ) -> None:
        self.config = config
        self.db = db
        self.preflight = preflight
        self.sizer = sizer
        self.paper = paper_broker or PaperBroker(db)
        self.policy = policy

    def submit(
        self,
        intent: TradeIntent,
        *,
        mid_price: float,
        equity_usd: float,
        portfolio_heat_pct: float = 0.0,
        corr_to_portfolio: float = 0.0,
        idempotency_key: str | None = None,
        gas_balances: dict[tuple[str, str], float] | None = None,
    ) -> OMSResult:
        mode = str(self.config.execution.mode)
        idem = idempotency_key or str(uuid.uuid4())

        # Intent events are emitted exclusively by engine.brain.decision (DecisionEngine).
        # Removed duplicate emission here to prevent double-counting in the event bus.

        pf = self.preflight.check(
            intent,
            mode=mode,
            equity_usd=float(equity_usd),
            gas_balances=gas_balances,
        )
        if not pf.approved:
            return OMSResult(status="rejected", mode=mode, reasons=pf.reasons)

        # Size notional (USD) - ignore intent.size_pct here; sizing uses conviction and caps.
        max_pct = float(self.config.risk.max_position_pct)
        notional = self.sizer.size_usd(
            equity_usd=float(equity_usd),
            conviction_score=max(0.0, min(1.0, float(intent.conviction_score) / 100.0)),
            corr_to_portfolio=float(corr_to_portfolio),
            portfolio_heat_pct=float(portfolio_heat_pct),
            max_position_pct=max_pct,
        )
        if notional <= 0:
            return OMSResult(status="rejected", mode=mode, reasons=["size_zero"])

        stop_loss = None
        take_profit = None
        # Short geometry inverts the map: risk is above entry, reward is below.
        # Get that wrong and every protective stop becomes a hidden liquidation trigger.
        # Mandelbrot in reverse: the dangerous tail for a short is up, not down.
        # Stops above entry are not optional geometry; they are survival math.
        if intent.stop_loss_pct is not None:
            if intent.direction == "short":
                stop_loss = float(mid_price) * (1.0 + float(intent.stop_loss_pct))
            else:
                stop_loss = float(mid_price) * (1.0 - float(intent.stop_loss_pct))
        if intent.take_profit_pct is not None:
            if intent.direction == "short":
                take_profit = float(mid_price) * (1.0 - float(intent.take_profit_pct))
            else:
                take_profit = float(mid_price) * (1.0 + float(intent.take_profit_pct))

        if mode == "paper":
            try:
                # Look up cts_score from conviction_scores table using conviction_id.
                _cts_at_entry: float | None = None
                if intent.conviction_id is not None:
                    try:
                        _cts_row = self.db.fetchone(
                            "SELECT cts_score FROM conviction_scores WHERE id = ?",
                            (intent.conviction_id,),
                        )
                        if _cts_row is not None and _cts_row[0] is not None:
                            _cts_at_entry = float(_cts_row[0])
                    except Exception:
                        pass  # cts_at_entry remains None — non-critical

                fill = self.paper.execute_market(
                    symbol=intent.symbol,
                    direction=intent.direction,
                    notional_usd=float(notional),
                    leverage=float(intent.leverage),
                    mid_price=float(mid_price),
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    idempotency_key=idem,
                    conviction_id=intent.conviction_id,
                    regime_at_entry=str(intent.regime) if intent.regime else None,
                    pcs_at_entry=float(intent.conviction_score),
                    cts_at_entry=_cts_at_entry,
                )
            except ValueError as _e:
                # Deduplication rejection: same symbol already has an open position.
                if "duplicate_open_position" in str(_e):
                    return OMSResult(status="rejected", mode=mode, reasons=[str(_e)])
                raise

            # Persist execution events (redundant with tables, but useful for the event bus).
            # dedupe_key anchors each event to its order/position so reconcile_execution_events()
            # can backfill idempotently after a crash between persist and event append.
            self.db.append_event(
                event_type=EventType.ORDER_SUBMITTED_V1,
                payload={
                    "order_id": fill.order_id,
                    "position_id": fill.position_id,
                    "venue": "paper",
                    "type": "market",
                    "side": fill.side,
                    "symbol": fill.symbol,
                    "size": float(fill.fill_size),
                    "idempotency_key": idem,
                },
                source="execution.oms",
                dedupe_key=f"order_submitted:{fill.order_id}",
            )
            self.db.append_event(
                event_type=EventType.ORDER_FILLED_V1,
                payload={
                    "order_id": fill.order_id,
                    "position_id": fill.position_id,
                    "fill_price": float(fill.fill_price),
                    "fill_size": float(fill.fill_size),
                    "fee_usd": float(fill.fee_usd),
                },
                source="execution.oms",
                dedupe_key=f"order_filled:{fill.order_id}",
            )
            self.db.append_event(
                event_type=EventType.POSITION_OPENED_V1,
                payload={
                    "position_id": fill.position_id,
                    "platform": "paper",
                    "asset": fill.symbol,
                    "direction": intent.direction,
                    "entry_price": float(fill.fill_price),
                    "size_notional": float(fill.notional_usd),
                    "leverage": float(intent.leverage),
                },
                source="execution.oms",
                dedupe_key=f"position_opened:{fill.position_id}",
            )

            # Emit SIGNAL_ACCEPTED_V1 for each contributing signal (flywheel attribution).
            # Canonical trade identity is position_id — pnl.py and karma.py both look up
            # attribution events by str(position_id), so we must emit with the same key.
            self._emit_signal_accepted(
                trade_id=fill.position_id,
                intent=intent,
            )

            # KS-5: Fill divergence check
            try:
                if intent.intended_price is not None and intent.intended_price > 0:
                    divergence = abs(fill.fill_price - intent.intended_price) / intent.intended_price
                    if divergence > 0.005:
                        self.preflight.kill_switch.evaluate(
                            manual_level=KillSwitchLevel.CAUTION,
                            reason=f"fill_divergence_{divergence:.4f}",
                        )
                        self.db.append_event(
                            event_type=EventType.AUDIT_V1,
                            payload={
                                "reason": "ks5_fill_divergence",
                                "intended": intent.intended_price,
                                "actual": fill.fill_price,
                                "divergence": divergence,
                            },
                            source="execution.oms",
                        )
            except Exception:
                import logging

                logging.getLogger("b1e55ed.execution.oms").warning("KS-5 fill divergence check failed", exc_info=True)

            return OMSResult(
                status="filled",
                mode=mode,
                order_id=fill.order_id,
                position_id=fill.position_id,
                notional_usd=float(notional),
            )

        if mode == "live":
            raise NotImplementedError("live execution adapter not implemented in Sprint 2A")

        return OMSResult(status="error", mode=mode, reasons=[f"unknown_mode:{mode}"])

    def _emit_signal_accepted(self, *, trade_id: str, intent: TradeIntent) -> None:
        """Emit SIGNAL_ACCEPTED_V1 for each source event that contributed to this trade.

        source_event_ids is the ONLY authoritative attribution source — injected from
        the synthesis snapshot at decision time. DB signal lookup is NOT used for
        normal-path attribution. Using recent DB signals would incorrectly credit any
        producer that happened to emit a signal for the same symbol in the last hour,
        even if their signal was never part of the synthesis snapshot that produced
        this trade.

        If source_event_ids is empty (e.g. legacy call sites or synthesis produced no
        events), a single ATTRIBUTION_GAP_V1 is emitted with producer_id='unknown' so
        that the missing attribution is explicitly recorded.  This is NOT a real
        SIGNAL_ACCEPTED_V1; downstream karma should ignore it.
        The fallback is NOT inflated with unrelated DB signals.
        """
        from engine.brain.synthesis import FeatureExtractor

        _log = logging.getLogger("b1e55ed.execution.oms")
        extractor = FeatureExtractor()

        # --- Build event_infos exclusively from intent.source_event_ids ---
        seen: set[str] = set()
        event_infos: list[tuple[str, str, str]] = []  # (event_id, type_str, source_str)

        for eid in intent.source_event_ids:
            if eid not in seen:
                seen.add(eid)
                irow = self.db.fetchone("SELECT type, source FROM events WHERE id = ?", (eid,))
                if irow is not None:
                    event_infos.append((eid, str(irow["type"]), str(irow["source"] or "unknown")))

        # --- Emit SIGNAL_ACCEPTED_V1 ---
        if not event_infos:
            # ATTRIBUTION_GAP_V1 — emitted when no source_event_ids available; not real attribution
            # Downstream consumers must treat this event type as "attribution missing",
            # not as a real producer credit.  signal_event_id='' signals no attributed signal.
            _log.debug(
                "_emit_signal_accepted: no signal events found for %s — emitting ATTRIBUTION_GAP_V1",
                intent.symbol,
            )
            fallback_payload = SignalAcceptedPayload(
                trade_id=trade_id,
                producer_id="unknown",
                domain="unknown",
                signal_event_id="",
                contribution_weight=1.0,
                direction=intent.direction,
                confidence=float(intent.conviction_score),
                horizon=intent.horizon,
                invalidation=intent.invalidation,
            ).model_dump(mode="json")
            self.db.append_event(
                event_type=EventType.ATTRIBUTION_GAP_V1,
                payload=fallback_payload,
                source="execution.oms",
                dedupe_key=f"signal_accepted:{trade_id}:fallback",
            )
            return

        for event_id, event_type_str, source in event_infos:
            # Derive domain from event type
            try:
                et = EventType(event_type_str)
                domain = extractor.DOMAIN_BY_EVENT_TYPE.get(et, "unknown")
            except ValueError:
                domain = "unknown"

            payload = SignalAcceptedPayload(
                trade_id=trade_id,
                producer_id=source,
                domain=domain,
                signal_event_id=event_id,
                contribution_weight=1.0,  # Phase 0: equal weights
                direction=intent.direction,
                confidence=float(intent.conviction_score),
                horizon=intent.horizon,
                invalidation=intent.invalidation,
            ).model_dump(mode="json")

            self.db.append_event(
                event_type=EventType.SIGNAL_ACCEPTED_V1,
                payload=payload,
                source="execution.oms",
                dedupe_key=f"signal_accepted:{trade_id}:{event_id}",
            )


_LOG = logging.getLogger("b1e55ed.execution.oms")


def _has_dedupe_key(db: Database, dedupe_key: str) -> bool:
    """Return True if *dedupe_key* already exists in the event_dedup table."""
    row = db.fetchone("SELECT 1 FROM event_dedup WHERE dedupe_key = ?", (dedupe_key,))
    return row is not None


def reconcile_execution_events(db: Database) -> dict[str, int]:
    """Scan all positions and backfill any missing provenance events.

    Idempotent: safe to run multiple times. Uses ``dedupe_key`` to prevent
    duplicate insertions. Returns a dict with the count of newly-emitted events
    by type.

    Call this at daemon startup (or via ``b1e55ed reconcile``) to repair the
    crash window between position persistence and event emission in the OMS.
    """
    log = logging.getLogger("b1e55ed.execution.oms.reconcile")
    counts: dict[str, int] = {
        "order_submitted": 0,
        "order_filled": 0,
        "position_opened": 0,
        "signal_accepted": 0,
    }

    rows = db.fetchall(
        """
        SELECT
            p.id       AS position_id,
            p.platform,
            p.asset,
            p.direction,
            p.entry_price,
            p.size_notional,
            p.leverage,
            o.id       AS order_id,
            o.venue,
            o.side,
            o.symbol,
            o.fill_price,
            o.fill_size,
            o.idempotency_key
        FROM positions p
        LEFT JOIN orders o ON o.position_id = p.id
        ORDER BY p.opened_at ASC
        """,
        (),
    )

    for _row in rows:
        row = dict(_row)
        position_id: str = row["position_id"]
        order_id: str | None = row.get("order_id")

        if order_id is None:
            continue  # position exists but no order yet — skip

        # ------------------------------------------------------------------ #
        # ORDER_SUBMITTED_V1                                                    #
        # ------------------------------------------------------------------ #
        dk_submitted = f"order_submitted:{order_id}"
        if not _has_dedupe_key(db, dk_submitted):
            db.append_event(
                event_type=EventType.ORDER_SUBMITTED_V1,
                payload={
                    "order_id": order_id,
                    "position_id": position_id,
                    "venue": row.get("venue") or "paper",
                    "type": "market",
                    "side": row.get("side") or "buy",
                    "symbol": row.get("symbol") or row.get("asset") or "",
                    "size": float(row.get("fill_size") or 0.0),
                    "idempotency_key": row.get("idempotency_key") or "",
                },
                source="execution.oms.reconcile",
                dedupe_key=dk_submitted,
            )
            counts["order_submitted"] += 1
            log.info("reconcile: backfilled ORDER_SUBMITTED_V1 for order %s", order_id)

        # ------------------------------------------------------------------ #
        # ORDER_FILLED_V1                                                       #
        # ------------------------------------------------------------------ #
        dk_filled = f"order_filled:{order_id}"
        if not _has_dedupe_key(db, dk_filled):
            db.append_event(
                event_type=EventType.ORDER_FILLED_V1,
                payload={
                    "order_id": order_id,
                    "position_id": position_id,
                    "fill_price": float(row.get("fill_price") or 0.0),
                    "fill_size": float(row.get("fill_size") or 0.0),
                    "fee_usd": 0.0,  # not stored in orders table; 0.0 on reconcile
                },
                source="execution.oms.reconcile",
                dedupe_key=dk_filled,
            )
            counts["order_filled"] += 1
            log.info("reconcile: backfilled ORDER_FILLED_V1 for order %s", order_id)

        # ------------------------------------------------------------------ #
        # POSITION_OPENED_V1                                                    #
        # ------------------------------------------------------------------ #
        dk_opened = f"position_opened:{position_id}"
        if not _has_dedupe_key(db, dk_opened):
            db.append_event(
                event_type=EventType.POSITION_OPENED_V1,
                payload={
                    "position_id": position_id,
                    "platform": row.get("platform") or "paper",
                    "asset": row.get("asset") or "",
                    "direction": row.get("direction") or "",
                    "entry_price": float(row.get("entry_price") or 0.0),
                    "size_notional": float(row.get("size_notional") or 0.0),
                    "leverage": float(row.get("leverage") or 1.0),
                },
                source="execution.oms.reconcile",
                dedupe_key=dk_opened,
            )
            counts["position_opened"] += 1
            log.info("reconcile: backfilled POSITION_OPENED_V1 for position %s", position_id)

        # ------------------------------------------------------------------ #
        # SIGNAL_ACCEPTED_V1                                                    #
        # The canonical trade_id in SIGNAL_ACCEPTED_V1 is position_id          #
        # (matches what _emit_signal_accepted uses and what pnl.py looks up).  #
        # ------------------------------------------------------------------ #
        existing_sa = db.fetchone(
            "SELECT id FROM events WHERE type = ? AND json_extract(payload, '$.trade_id') = ? LIMIT 1",
            (EventType.SIGNAL_ACCEPTED_V1.value, position_id),
        )
        dk_sa = f"signal_accepted:{position_id}:reconciled"
        if existing_sa is None and not _has_dedupe_key(db, dk_sa):
            _sa_payload = SignalAcceptedPayload(
                trade_id=position_id,
                producer_id="reconciled",
                domain="unknown",
                signal_event_id=position_id,  # placeholder
                contribution_weight=1.0,
                direction=row.get("direction") or "long",
                confidence=0.0,  # unknown at reconcile time
            ).model_dump(mode="json")
            # recovery_placeholder=True marks synthetic backfill — not real signal attribution
            _sa_payload["recovery_placeholder"] = True
            db.append_event(
                event_type=EventType.SIGNAL_ACCEPTED_V1,
                payload=_sa_payload,
                source="execution.oms.reconcile",
                dedupe_key=dk_sa,
            )
            counts["signal_accepted"] += 1
            log.info("reconcile: backfilled SIGNAL_ACCEPTED_V1 for position %s", position_id)

    total = sum(counts.values())
    log.info("reconcile_execution_events complete: %d events backfilled — %s", total, counts)
    return counts


def default_sizer_from_config(cfg: Config) -> CorrelationAwareSizer:
    base = PositionSizer(
        kelly=None,
        limits=RiskLimits(max_position_pct=float(cfg.risk.max_position_pct), min_position_usd=10.0),
    )
    return CorrelationAwareSizer(base)
