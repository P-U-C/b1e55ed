"""engine.brain.orchestrator

The decomposed brain orchestrator.

"The conductor does not play the instruments." (Easter egg)

This class coordinates a single brain cycle. It is a coordinator, not an
implementor. All logic is delegated to specialized modules.

Pipeline:
1) Pre-cycle hooks
2) Data quality check
3) Synthesis v2 (feature snapshots)
4) Regime detection
5) Conviction scoring (PCS + CTS)
6) Decision engine (intent generation)
7) Post-cycle hooks

"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    UTC = UTC  # noqa: N806


from engine.brain.conviction import ConvictionEngine, ConvictionResult
from engine.brain.data_quality import DataQualityMonitor, DataQualityResult
from engine.brain.decision import DecisionEngine
from engine.brain.hooks import BrainHooks, PostCycleContext, PreCycleContext
from engine.brain.kill_switch import KillSwitch, KillSwitchDecision, KillSwitchLevel
from engine.brain.learning import StratificationTracker
from engine.brain.regime import RegimeDetector, RegimeResult
from engine.brain.synthesis import SynthesisResult, VectorSynthesis
from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType, canonical_json
from engine.core.types import TradeIntent
from engine.security.identity import NodeIdentity


@dataclass(frozen=True, slots=True)
class CycleResult:
    cycle_id: str
    ts: datetime
    data_quality: DataQualityResult
    kill_switch: KillSwitchDecision | None
    regime: RegimeResult
    synthesis: dict[str, SynthesisResult]
    convictions: dict[str, ConvictionResult]
    intents: list[dict]


class BrainOrchestrator:
    def __init__(
        self,
        config: Config,
        db: Database,
        identity: NodeIdentity,
        oms=None,  # OMS | None — injected to avoid execution→brain layer violation
    ):
        self.config = config
        self.db = db
        self.identity = identity
        self._oms = oms  # injected; avoids execution layer import at brain layer

        self.hooks = BrainHooks(config, db)
        self.data_quality = DataQualityMonitor(config, db)
        self.synthesis = VectorSynthesis(config, db)
        self.regime = RegimeDetector(db)
        self.kill_switch = KillSwitch(config, db)
        self.conviction = ConvictionEngine(config, db, node_id=identity.node_id)
        self.decision = DecisionEngine(config, db)
        self.stratification = StratificationTracker(db)
        self._domain_miss_counts: dict[str, int] = {}

    def run_cycle(self, symbols: list[str]) -> CycleResult:
        # Abort immediately if kill switch is active.
        ks_level = self.kill_switch.level
        if int(ks_level) >= int(KillSwitchLevel.DEFENSIVE):
            logging.getLogger("b1e55ed.orchestrator").warning("Brain cycle aborted: kill switch level %s is active", ks_level)
            raise RuntimeError(f"Brain cycle blocked by kill switch (level={ks_level})")

        cycle_id = str(uuid.uuid4())
        now = datetime.now(tz=UTC)

        self.hooks.pre_cycle(PreCycleContext(config=self.config, db=self.db, cycle_id=cycle_id))

        dq = self.data_quality.evaluate(as_of=now)
        # Use data quality to adjust weights (domain -> multiplier)
        q_mult = dict(dq.per_domain_quality)  # mutable copy

        # KS-4: Data feed degradation
        try:
            domains = list(q_mult.keys())
            degraded_domains = []
            for domain in domains:
                quality = q_mult.get(domain, 1.0)
                if quality <= 0.0:
                    self._domain_miss_counts[domain] = self._domain_miss_counts.get(domain, 0) + 1
                else:
                    self._domain_miss_counts[domain] = 0
                if self._domain_miss_counts.get(domain, 0) >= 2:
                    degraded_domains.append(domain)

            for domain in degraded_domains:
                q_mult[domain] = 0.0

            if degraded_domains and len(degraded_domains) >= len(domains) and len(domains) > 0:
                self.kill_switch.evaluate(manual_level=KillSwitchLevel.CAUTION, reason="all_domains_degraded")
        except Exception:
            logging.getLogger("b1e55ed.orchestrator").warning("KS-4 degradation check failed", exc_info=True)

        # Emit a cycle marker (useful for auditing)
        self.db.append_event(
            event_type=EventType.BRAIN_CYCLE_V1,
            payload={"cycle_id": cycle_id, "symbols": [s.upper() for s in symbols]},
            source="brain.orchestrator",
            trace_id=cycle_id,
        )

        synth_results: dict[str, SynthesisResult] = {}
        for sym in symbols:
            synth_results[sym.upper()] = self.synthesis.synthesize(
                cycle_id=cycle_id,
                symbol=sym,
                as_of=now,
                quality_adjustment=q_mult,
            )
            # Persist feature snapshot row (reproducibility)
            snap = synth_results[sym.upper()].snapshot
            with self.db.conn:
                self.db.conn.execute(
                    """
                    INSERT INTO feature_snapshots (cycle_id, symbol, ts, features, source_event_ids, regime, version)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snap.cycle_id,
                        snap.symbol,
                        snap.ts.isoformat(),
                        canonical_json(snap.features),
                        canonical_json(snap.source_event_ids),
                        snap.regime,
                        snap.version,
                    ),
                )

                # Contributor attribution: mark signals that made it into synthesis as accepted.
                if snap.source_event_ids:
                    placeholders = ",".join(["?"] * len(snap.source_event_ids))
                    self.db.conn.execute(
                        f"UPDATE contributor_signals SET accepted = 1 WHERE event_id IN ({placeholders})",
                        tuple(snap.source_event_ids),
                    )

            # Emit immutable audit event for accepted signals so acceptance
            # decisions are part of the hash-chained event log.
            if snap.source_event_ids:
                self.db.append_event(
                    event_type=EventType.SIGNAL_ACCEPTED_V1,
                    payload={
                        "cycle_id": cycle_id,
                        "event_ids": list(snap.source_event_ids),
                        "symbol": sym,
                        "accepted_count": len(snap.source_event_ids),
                    },
                    source="brain.orchestrator",
                    trace_id=cycle_id,
                )

        # Regime from BTC when available, else transition.
        btc = synth_results.get("BTC")
        regime_res = self.regime.detect(as_of=now, btc_snapshot=(btc.snapshot if btc else None))
        self.regime.emit_if_changed(regime_res)

        # Kill switch escalation if crisis.
        ks_dec = None
        if regime_res.state.regime == "CRISIS":
            ks_dec = self.kill_switch.evaluate(crisis_conditions=self.config.kill_switch.l3_crisis_threshold, reason="regime_crisis")

        convictions: dict[str, ConvictionResult] = {}
        intents: list[dict] = []

        for sym, synth in synth_results.items():
            conv = self.conviction.compute(synthesis=synth, regime=regime_res.state.regime, as_of=now)
            convictions[sym] = conv
            self.conviction.emit(conv, cycle_id=cycle_id)

            # S7: Record signal for stratification tracking
            self.stratification.record_signal(
                signal_id=f"{cycle_id}:{sym}",
                symbol=sym,
                confidence=conv.score.confidence or 0.0,
                direction=conv.score.direction,
                ts=now,
            )

            intent = self.decision.decide_and_emit(
                symbol=sym,
                pcs=conv.final_conviction,
                regime=regime_res.state.regime,
                kill_level=self.kill_switch.level,
                trace_id=cycle_id,
            )
            if intent is not None:
                # TradeIntent is a frozen slots dataclass.
                from dataclasses import asdict

                intents.append(asdict(intent))

        # S7: Auto-paper-trade on high confidence
        if getattr(self.config.brain, "auto_paper_trade", True):
            _log = logging.getLogger("b1e55ed.orchestrator")
            for sym, conv in convictions.items():
                confidence = conv.score.confidence or 0.0
                if confidence >= 0.65 and self.kill_switch.level == KillSwitchLevel.SAFE:
                    try:
                        direction = conv.score.direction if conv.score.direction != "neutral" else "long"
                        ti = TradeIntent(
                            symbol=sym,
                            direction=direction,
                            size_pct=0.02,
                            leverage=1.0,
                            conviction_score=conv.final_conviction,
                            regime=regime_res.state.regime,
                            rationale="auto_paper_trade:high_confidence",
                            stop_loss_pct=0.05,
                            take_profit_pct=0.10,
                        )
                        if self._oms is None:
                            _log.warning("auto-paper-trade skipped: no OMS injected")
                            continue
                        oms_result = self._oms.submit(ti, mid_price=1.0, equity_usd=10000.0)
                        _log.info("auto-paper-trade: %s %s -> %s", sym, direction, oms_result.status)
                    except Exception:
                        _log.exception("auto-paper-trade failed for %s -- brain cycle continues", sym)
                elif 0.45 <= confidence < 0.65:
                    _log.info("watch: %s confidence=%.2f", sym, confidence)
                elif confidence < 0.45:
                    _log.debug("low conviction: %s confidence=%.2f", sym, confidence)

        result = CycleResult(
            cycle_id=cycle_id,
            ts=now,
            data_quality=dq,
            kill_switch=ks_dec,
            regime=regime_res,
            synthesis=synth_results,
            convictions=convictions,
            intents=intents,
        )

        self.hooks.post_cycle(PostCycleContext(config=self.config, db=self.db, cycle_id=cycle_id, result=result))
        return result
