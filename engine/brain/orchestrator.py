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

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from engine.brain.conviction import ConvictionEngine, ConvictionResult
from engine.brain.data_quality import DataQualityMonitor, DataQualityResult
from engine.brain.decision import DecisionEngine
from engine.brain.hooks import BrainHooks, PostCycleContext, PreCycleContext
from engine.brain.kill_switch import KillSwitch, KillSwitchDecision
from engine.brain.regime import RegimeDetector, RegimeResult
from engine.brain.synthesis import SynthesisResult, VectorSynthesis
from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType, canonical_json
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
    def __init__(self, config: Config, db: Database, identity: NodeIdentity):
        self.config = config
        self.db = db
        self.identity = identity

        self.hooks = BrainHooks(config, db)
        self.data_quality = DataQualityMonitor(config, db)
        self.synthesis = VectorSynthesis(config, db)
        self.regime = RegimeDetector(db)
        self.kill_switch = KillSwitch(config, db)
        self.conviction = ConvictionEngine(config, db, node_id=identity.node_id)
        self.decision = DecisionEngine(config, db)

    def run_cycle(self, symbols: list[str]) -> CycleResult:
        cycle_id = str(uuid.uuid4())
        now = datetime.now(tz=UTC)

        self.hooks.pre_cycle(PreCycleContext(config=self.config, db=self.db, cycle_id=cycle_id))

        dq = self.data_quality.evaluate(as_of=now)
        # Use data quality to adjust weights (domain -> multiplier)
        q_mult = dq.per_domain_quality

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
