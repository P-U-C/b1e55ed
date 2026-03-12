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
from time import perf_counter

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017


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

    def _resolve_mid_price(self, symbol: str) -> float | None:
        """Resolve mid price for a symbol.

        Strategy:
        1. Query most recent PRICE_V1 event from the DB
        2. Fallback: query Binance public ticker API
        3. Returns None if no price available (caller should skip the trade)
        """
        _log = logging.getLogger("b1e55ed.orchestrator")

        # 1) Try DB: most recent price event for this symbol
        try:
            row = self.db.fetchone(
                """
                SELECT payload FROM events
                WHERE type = 'PRICE_V1'
                  AND json_extract(payload, '$.symbol') = ?
                ORDER BY ts DESC LIMIT 1
                """,
                (symbol.upper(),),
            )
            if row is not None:
                import json as _json

                payload = _json.loads(row[0]) if isinstance(row[0], str) else row[0]
                price = 0.0
                for _pk in ("price", "close", "mid"):
                    _pv = payload.get(_pk)
                    if _pv is not None:
                        price = float(_pv)
                        break
                if price > 0:
                    _log.debug("mid_price for %s from DB: %.4f", symbol, price)
                    return price
        except Exception:
            _log.debug("DB price lookup failed for %s", symbol, exc_info=True)

        # 2) Fallback: Binance public API (no auth required)
        try:
            import urllib.request

            ticker_symbol = f"{symbol.upper()}USDT"
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={ticker_symbol}"
            req = urllib.request.Request(url, headers={"User-Agent": "b1e55ed/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                import json as _json

                data = _json.loads(resp.read())
                price = float(data.get("price", 0))
                if price > 0:
                    _log.debug("mid_price for %s from Binance: %.4f", symbol, price)
                    return price
        except Exception:
            _log.debug("Binance price lookup failed for %s", symbol, exc_info=True)

        return None

    def run_cycle(self, symbols: list[str]) -> CycleResult:
        # Abort immediately if kill switch is active.
        ks_level = self.kill_switch.level
        if int(ks_level) >= int(KillSwitchLevel.DEFENSIVE):
            logging.getLogger("b1e55ed.orchestrator").warning("Brain cycle aborted: kill switch level %s is active", ks_level)
            raise RuntimeError(f"Brain cycle blocked by kill switch (level={ks_level})")

        cycle_id = str(uuid.uuid4())
        cycle_started_at = datetime.now(tz=UTC)
        cycle_started_perf = perf_counter()
        now = cycle_started_at
        symbols_upper = [s.upper() for s in symbols]

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

        synth_results: dict[str, SynthesisResult] = {}
        synthesize_with_regime = getattr(self.synthesis, "synthesize_with_regime", None)

        for sym in symbols:
            sym_upper = sym.upper()
            if callable(synthesize_with_regime):
                try:
                    synth_results[sym_upper] = synthesize_with_regime(
                        cycle_id=cycle_id,
                        symbol=sym,
                        as_of=now,
                        quality_adjustment=q_mult,
                        regime_detector=self.regime,
                    )
                except Exception:
                    logging.getLogger("b1e55ed.orchestrator").warning(
                        "synthesize_with_regime failed for %s; falling back to synthesize()",
                        sym_upper,
                        exc_info=True,
                    )
                    synth_results[sym_upper] = self.synthesis.synthesize(
                        cycle_id=cycle_id,
                        symbol=sym,
                        as_of=now,
                        quality_adjustment=q_mult,
                    )
            else:
                synth_results[sym_upper] = self.synthesis.synthesize(
                    cycle_id=cycle_id,
                    symbol=sym,
                    as_of=now,
                    quality_adjustment=q_mult,
                )

            # Persist feature snapshot row (reproducibility)
            snap = synth_results[sym_upper].snapshot
            with self.db._lock, self.db.conn:
                self.db.execute(
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
                    self.db.execute(
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
                confidence = float(conv.score.confidence or 0.0)
                magnitude = float(conv.score.magnitude or 0.0)
                final_conviction = float(conv.final_conviction or 0.0)

                min_conf = float(getattr(self.config.brain, "auto_paper_trade_min_confidence", 0.35) or 0.35)

                # Primary trigger: calibrated confidence.
                # Fallback trigger: very strong directional conviction even when confidence calibration is conservative.
                strong_directional = conv.score.direction != "neutral" and magnitude >= 6.5 and (final_conviction >= 80.0 or final_conviction <= 20.0)

                should_auto_trade = confidence >= min_conf or strong_directional

                if should_auto_trade and self.kill_switch.level == KillSwitchLevel.SAFE:
                    try:
                        direction = conv.score.direction if conv.score.direction != "neutral" else "long"

                        # Resolve mid_price from DB price events or Binance API
                        # Resolve mid_price from DB price events or Binance API
                        mid_price = self._resolve_mid_price(sym)
                        if mid_price is None:
                            _log.warning("auto-paper-trade skipped for %s: no price available", sym)
                            continue

                        # Look up conviction_id from the most recent conviction_scores row
                        _conv_id = None
                        try:
                            _row = self.db.fetchone(
                                "SELECT id FROM conviction_scores WHERE cycle_id = ? AND symbol = ? ORDER BY id DESC LIMIT 1",
                                (cycle_id, sym),
                            )
                            if _row is not None:
                                _conv_id = int(_row[0])
                        except Exception:
                            _log.debug("conviction_id lookup failed for %s", sym, exc_info=True)

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
                            intended_price=mid_price,
                            conviction_id=_conv_id,
                        )
                        if self._oms is None:
                            _log.warning("auto-paper-trade skipped: no OMS injected")
                            continue
                        oms_result = self._oms.submit(ti, mid_price=mid_price, equity_usd=10000.0)
                        _log.info("auto-paper-trade: %s %s @ %.2f -> %s", sym, direction, mid_price, oms_result.status)
                    except Exception:
                        _log.exception("auto-paper-trade failed for %s -- brain cycle continues", sym)
                elif 0.45 <= confidence < 0.65:
                    _log.info("watch: %s confidence=%.2f", sym, confidence)
                elif confidence < 0.45:
                    _log.debug("low conviction: %s confidence=%.2f", sym, confidence)

        # Fowler's event sourcing invariant: state is the function of events, not the inverse.
        # This cycle event now carries enough state to reconstruct the moment entirely.
        domain_scores_payload: dict[str, dict[str, float]] = {}
        regime_payload: dict[str, str] = {}
        feature_vectors_payload: dict[str, dict[str, dict[str, float]]] = {}

        for sym in symbols_upper:
            synth = synth_results.get(sym)
            if synth is None:
                domain_scores_payload[sym] = {}
                regime_payload[sym] = "unknown"
                feature_vectors_payload[sym] = {}
                continue

            domain_scores_payload[sym] = {domain: float(score) for domain, score in synth.domain_scores.items()}
            regime_payload[sym] = str(getattr(synth, "regime_tag", "") or "unknown")
            feature_vectors_payload[sym] = {
                domain: {key: float(value) for key, value in feature_map.items()} for domain, feature_map in synth.snapshot.features.items()
            }

        conviction_payload: dict[str, dict[str, float | str | bool | None]] = {}
        for sym, conv in convictions.items():
            conviction_payload[sym] = {
                "pcs": float(conv.pcs),
                "magnitude": float(conv.score.magnitude),
                "direction": str(conv.score.direction),
                "capped_by_regime": bool(conv.capped_by_regime),
                "pre_cap_magnitude": float(conv.pre_cap_magnitude) if conv.pre_cap_magnitude is not None else None,
            }

        cycle_emitted_at = datetime.now(tz=UTC)
        forecast_ids_payload: dict[str, list[str]] = {sym: [] for sym in symbols_upper}
        try:
            forecast_events = self.db.get_events(
                event_type=EventType.FORECAST_V1,
                since=cycle_started_at,
                until=cycle_emitted_at,
                limit=5000,
            )
            for ev in reversed(forecast_events):
                payload = ev.payload if isinstance(ev.payload, dict) else {}
                forecast_symbol = str(payload.get("asset") or payload.get("symbol") or "").upper()
                if forecast_symbol in forecast_ids_payload:
                    forecast_ids_payload[forecast_symbol].append(ev.id)
        except Exception:
            logging.getLogger("b1e55ed.orchestrator").warning(
                "Failed to collect FORECAST_V1 ids for cycle %s",
                cycle_id,
                exc_info=True,
            )

        # Heraclitus: you cannot step into the same cycle twice. The duration is proof it happened. The snapshot is proof of what it was.
        cycle_duration_ms = max(0, int((perf_counter() - cycle_started_perf) * 1000))

        self.db.append_event(
            event_type=EventType.BRAIN_CYCLE_V1,
            payload={
                "cycle_id": cycle_id,
                "symbols": symbols_upper,
                "domain_scores": domain_scores_payload,
                "regime": regime_payload,
                "conviction": conviction_payload,
                "forecast_ids": forecast_ids_payload,
                "feature_vectors": feature_vectors_payload,
                "cycle_duration_ms": cycle_duration_ms,
                "ts": cycle_emitted_at.isoformat(),
            },
            source="brain.orchestrator",
            trace_id=cycle_id,
        )

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
