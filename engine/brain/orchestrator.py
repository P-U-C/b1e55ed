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
from dataclasses import dataclass, field
from datetime import datetime
from time import perf_counter
from typing import Any

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017


from engine.brain.conviction import ConvictionEngine, ConvictionResult
from engine.brain.conviction_v2_bridge import compute_v2_overrides, detect_regime_v2
from engine.brain.data_quality import DataQualityMonitor, DataQualityResult
from engine.brain.decision import DecisionEngine
from engine.brain.hooks import BrainHooks, PostCycleContext, PreCycleContext
from engine.brain.kill_switch import KillSwitch, KillSwitchDecision, KillSwitchLevel, PauseGate
from engine.brain.learning import StratificationTracker
from engine.brain.regime import RegimeDetector, RegimeResult
from engine.brain.regime_v2 import RegimeDetectorV2
from engine.brain.synthesis import SynthesisResult, VectorSynthesis
from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType, canonical_json
from engine.core.kill_switch_alerts import notify_kill_switch_escalated
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


@dataclass(frozen=True, slots=True)
class AutoTradePolicyDecision:
    allowed: bool
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


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
        self._regime_v2 = RegimeDetectorV2(db) if getattr(config.brain, "use_regime_v2", False) else None
        self.kill_switch = KillSwitch(config, db)
        self.pause_gate = PauseGate(db)
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
                WHERE type IN ('signal.price_ws.v1', 'PRICE_V1')
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

        # 2) Fallback: CoinGecko for HYPE, then Binance
        cg_map = {"HYPE": "hyperliquid"}
        sym_upper = symbol.upper()
        if sym_upper in cg_map:
            try:
                import urllib.request

                cg_id = cg_map[sym_upper]
                url = f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd"
                req = urllib.request.Request(url, headers={"User-Agent": "b1e55ed/1.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    import json as _json

                    data = _json.loads(resp.read())
                    price = float(data.get(cg_id, {}).get("usd", 0))
                    if price > 0:
                        _log.debug("mid_price for %s from CoinGecko: %.4f", symbol, price)
                        return price
            except Exception:
                _log.debug("CoinGecko price lookup failed for %s", symbol, exc_info=True)
            return None
        try:
            import urllib.request

            ticker_symbol = f"{sym_upper}USDT"
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

    @staticmethod
    def _normalize_list(values: Any, *, upper: bool = False) -> list[str]:
        vals = values if isinstance(values, list) else []
        out: list[str] = []
        seen: set[str] = set()
        for raw in vals:
            item = str(raw or "").strip()
            if not item:
                continue
            item = item.upper() if upper else item.lower()
            if item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out

    def _bundle_auto_trade_policy(self, symbol: str) -> AutoTradePolicyDecision:
        """Resolve whether auto execution is allowed for this symbol.

        Backward compatibility rule:
        - no bundles configured => allow legacy behavior
        """

        sym = str(symbol or "").strip().upper()
        if not sym:
            return AutoTradePolicyDecision(allowed=False, reason="invalid_symbol", metadata={"symbol": symbol})

        universe = getattr(self.config, "universe", None)
        if universe is None:
            return AutoTradePolicyDecision(allowed=True, reason=None, metadata={"policy_mode": "legacy_no_universe"})

        try:
            enabled_bundles_fn = getattr(universe, "enabled_bundles", None)
            if callable(enabled_bundles_fn):
                enabled_bundles = list(enabled_bundles_fn())
            else:
                bundles = getattr(universe, "bundles", [])
                enabled_bundles = [b for b in bundles if bool(getattr(b, "enabled", True))]
        except Exception:
            logging.getLogger("b1e55ed.orchestrator").debug("bundle policy lookup failed; using legacy allow", exc_info=True)
            return AutoTradePolicyDecision(allowed=True, reason=None, metadata={"policy_mode": "legacy_bundle_lookup_error"})

        if not enabled_bundles:
            return AutoTradePolicyDecision(allowed=True, reason=None, metadata={"policy_mode": "legacy_no_bundles"})

        metadata_fn = getattr(universe, "execution_metadata_for_symbol", None)
        metadata: dict[str, Any]
        if callable(metadata_fn):
            raw_meta = metadata_fn(sym)
            metadata = dict(raw_meta) if isinstance(raw_meta, dict) else {}
        else:
            symbol_bundles = [b for b in enabled_bundles if sym in self._normalize_list(getattr(b, "symbols", []), upper=True)]
            metadata = {
                "bundle_ids": [str(getattr(b, "id", "")) for b in symbol_bundles],
                "asset_classes": [str(getattr(b, "asset_class", "")).lower() for b in symbol_bundles],
                "venues": [str(getattr(b, "venue", "")).lower() for b in symbol_bundles],
                "tags": [tag for b in symbol_bundles for tag in self._normalize_list(getattr(b, "tags", []))],
                "execution_mode_hints": [
                    str(getattr(b, "execution_mode_hint", "")).lower() for b in symbol_bundles if str(getattr(b, "execution_mode_hint", "")).strip()
                ],
            }

        bundle_ids = self._normalize_list(metadata.get("bundle_ids", []), upper=False)
        asset_classes = self._normalize_list(metadata.get("asset_classes", []), upper=False)
        venues = self._normalize_list(metadata.get("venues", []), upper=False)
        tags = self._normalize_list(metadata.get("tags", []), upper=False)
        mode_hints = self._normalize_list(metadata.get("execution_mode_hints", []), upper=False)

        policy_meta = {
            "symbol": sym,
            "bundle_ids": bundle_ids,
            "asset_classes": asset_classes,
            "venues": venues,
            "tags": tags,
            "execution_mode_hints": mode_hints,
        }

        if not bundle_ids:
            return AutoTradePolicyDecision(
                allowed=False,
                reason="symbol_not_in_active_bundle",
                metadata=policy_meta,
            )

        deny_tags = {
            "no-trade",
            "no_trade",
            "observe-only",
            "observe_only",
            "signal-only",
            "signal_only",
            "conviction-only",
            "conviction_only",
            "watchlist-only",
            "watchlist_only",
        }
        deny_hints = {
            "disabled",
            "off",
            "none",
            "signal_only",
            "signal-only",
            "conviction_only",
            "conviction-only",
            "observe_only",
            "observe-only",
            "no_trade",
            "no-trade",
        }

        if any(tag in deny_tags for tag in tags):
            return AutoTradePolicyDecision(allowed=False, reason="execution_tag_blocks_execution", metadata=policy_meta)

        if any(hint in deny_hints for hint in mode_hints):
            return AutoTradePolicyDecision(allowed=False, reason="execution_mode_hint_blocks_execution", metadata=policy_meta)

        execution_cfg = getattr(self.config, "execution", None)
        runtime_mode = str(getattr(execution_cfg, "mode", "paper") or "paper").strip().lower()

        restricted_modes: set[str] = set()
        for hint in mode_hints:
            if hint in {"paper_only", "paper-only"}:
                restricted_modes.add("paper")
            elif hint in {"live_only", "live-only"}:
                restricted_modes.add("live")

        if restricted_modes and runtime_mode not in restricted_modes:
            return AutoTradePolicyDecision(
                allowed=False,
                reason="execution_mode_hint_mismatch",
                metadata={**policy_meta, "runtime_mode": runtime_mode, "allowed_modes": sorted(restricted_modes)},
            )

        allowed_asset_classes = self._normalize_list(getattr(execution_cfg, "allowed_bundle_asset_classes", ["crypto"]), upper=False)
        if asset_classes and allowed_asset_classes and not set(asset_classes).intersection(allowed_asset_classes):
            return AutoTradePolicyDecision(
                allowed=False,
                reason="asset_class_not_allowed",
                metadata={**policy_meta, "allowed_asset_classes": allowed_asset_classes},
            )

        allowed_venues = self._normalize_list(
            getattr(execution_cfg, "allowed_bundle_venues", ["global", "paper", "hyperliquid", "binance", "coinbase"]),
            upper=False,
        )
        if venues and allowed_venues and not set(venues).intersection(allowed_venues):
            return AutoTradePolicyDecision(
                allowed=False,
                reason="venue_not_allowed",
                metadata={**policy_meta, "allowed_venues": allowed_venues},
            )

        return AutoTradePolicyDecision(allowed=True, reason=None, metadata=policy_meta)

    def _emit_execution_gate_event(self, *, symbol: str, cycle_id: str, decision: AutoTradePolicyDecision) -> None:
        try:
            self.db.append_event(
                event_type=EventType.AUDIT_V1,
                payload={
                    "reason": "execution_gated_by_bundle_policy",
                    "gate_reason": str(decision.reason or "unknown"),
                    "symbol": str(symbol).upper(),
                    "details": dict(decision.metadata),
                    "cycle_id": cycle_id,
                },
                source="brain.orchestrator",
                trace_id=cycle_id,
            )
        except Exception:
            logging.getLogger("b1e55ed.orchestrator").debug(
                "failed to emit execution gate audit event for %s",
                symbol,
                exc_info=True,
            )

    def run_cycle(self, symbols: list[str]) -> CycleResult:
        # Abort immediately if kill switch is active.
        ks_level = self.kill_switch.level
        if int(ks_level) >= int(KillSwitchLevel.DEFENSIVE):
            logging.getLogger("b1e55ed.orchestrator").warning("Brain cycle aborted: kill switch level %s is active", ks_level)
            raise RuntimeError(f"Brain cycle blocked by kill switch (level={ks_level})")

        paused, pause_reason = self.pause_gate.is_paused()
        if paused:
            reason = str(pause_reason or "operator pause")
            _log = logging.getLogger("b1e55ed.orchestrator")
            _log.warning("Brain cycle paused by operator: %s", reason)
            self.pause_gate.consume()
            raise RuntimeError(f"Brain cycle paused: {reason}")

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
                degraded_ks_dec = self.kill_switch.evaluate(manual_level=KillSwitchLevel.CAUTION, reason="all_domains_degraded")
                if degraded_ks_dec is not None:
                    notify_kill_switch_escalated(
                        previous_level=int(degraded_ks_dec.previous_level),
                        level=int(degraded_ks_dec.level),
                        level_name=degraded_ks_dec.level.name,
                        reason=degraded_ks_dec.reason,
                    )
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
            # NOTE: SIGNAL_ACCEPTED_V1 requires {trade_id, producer_id, domain, signal_event_id,
            # direction, confidence} — those are only available after a trade is submitted.
            # At synthesis time we emit AUDIT_V1 to preserve the bulk-acceptance record.
            # The canonical SIGNAL_ACCEPTED_V1 events (one per signal) are emitted by OMS._emit_signal_accepted().
            if snap.source_event_ids:
                self.db.append_event(
                    event_type=EventType.AUDIT_V1,
                    payload={
                        "reason": "signals_ingested_for_cycle",
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

        # V2 regime (parallel, for feature-flagged path)
        _regime_v2_result = detect_regime_v2(self._regime_v2, btc.snapshot if btc else None)

        # Kill switch escalation if crisis.
        ks_dec = None
        if regime_res.state.regime == "CRISIS":
            ks_dec = self.kill_switch.evaluate(crisis_conditions=self.config.kill_switch.l3_crisis_threshold, reason="regime_crisis")
            if ks_dec is not None:
                notify_kill_switch_escalated(
                    previous_level=int(ks_dec.previous_level),
                    level=int(ks_dec.level),
                    level_name=ks_dec.level.name,
                    reason=ks_dec.reason,
                )

        convictions: dict[str, ConvictionResult] = {}
        intents: list[dict] = []

        for sym, synth in synth_results.items():
            # Compute v2 overrides (regime multiplier + CTS) when flag is on
            cal = getattr(self.config.brain, "cts_calibration", None)
            cal_dict = cal.model_dump() if cal is not None else None
            v2 = compute_v2_overrides(_regime_v2_result, synth.snapshot.features, cal_dict)

            # Extract dominant horizon from contributing forecast events.
            # Most recent/frequent horizon wins; default to "4h" if none found.
            _dominant_horizon = "4h"
            try:
                _src_ids = list(synth.snapshot.source_event_ids or [])
                if _src_ids:
                    _ph = ",".join("?" * len(_src_ids))
                    _h_rows = self.db.fetchall(
                        f"SELECT json_extract(payload, '$.horizon') as h FROM events WHERE id IN ({_ph}) AND h IS NOT NULL",
                        tuple(_src_ids),
                    )
                    _horizons = [str(r[0]) for r in _h_rows if r[0]]
                    if _horizons:
                        from collections import Counter
                        _dominant_horizon = Counter(_horizons).most_common(1)[0][0]
            except Exception:
                pass  # fall back to "4h"

            conv = self.conviction.compute(
                synthesis=synth,
                regime=v2.regime_label if v2 else regime_res.state.regime,
                as_of=now,
                timeframe=_dominant_horizon,
                regime_multiplier_v2=v2.regime_multiplier if v2 else None,
                cts_v2=v2.cts if v2 else None,
            )
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
                source_event_ids=list(synth.snapshot.source_event_ids or []),
                horizon=conv.score.timeframe,
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
                    gate_decision = self._bundle_auto_trade_policy(sym)
                    if not gate_decision.allowed:
                        _log.info(
                            "execution_gated_by_bundle_policy: symbol=%s gate_reason=%s metadata=%s",
                            sym,
                            gate_decision.reason,
                            gate_decision.metadata,
                        )
                        self._emit_execution_gate_event(symbol=sym, cycle_id=cycle_id, decision=gate_decision)
                        continue

                    # Fix 1: Hard gate — skip neutral or missing direction.
                    # Never open a position on a neutral conviction; neutral means "no edge".
                    _direction = str(conv.score.direction or "").strip().lower()
                    if not _direction or _direction == "neutral":
                        _log.info("auto-paper-trade skipped: %s direction is neutral/missing", sym)
                        continue

                    # Fix 2: Minimum magnitude threshold — low-magnitude signals lack conviction.
                    min_magnitude = float(getattr(self.config.brain, "auto_paper_trade_min_magnitude", 5.0) or 5.0)
                    if min_magnitude < 3.0:
                        _log.warning(
                            "auto_paper_trade_min_magnitude=%.1f is below 3.0 — "
                            "this will trigger trades on weak signals. "
                            "Suitable for testing only; raise to ≥5.0 before live trading.",
                            min_magnitude,
                        )
                    if magnitude < min_magnitude:
                        _log.info(
                            "auto-paper-trade skipped: %s magnitude %.2f < %.2f threshold",
                            sym,
                            magnitude,
                            min_magnitude,
                        )
                        continue

                    try:
                        direction = _direction  # already validated above; cannot be neutral or empty

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
                            horizon=conv.score.timeframe,  # signal-driven hold duration
                            intended_price=mid_price,
                            conviction_id=_conv_id,
                            source_event_ids=list(synth_results[sym].snapshot.source_event_ids or []),
                        )
                        if self._oms is None:
                            _log.warning("auto-paper-trade skipped: no OMS injected")
                            continue
                        oms_result = self._oms.submit(ti, mid_price=mid_price, equity_usd=float(self.config.risk.portfolio_value_usd))
                        _log.info("auto-paper-trade: %s %s @ %.2f -> %s", sym, direction, mid_price, oms_result.status)
                    except Exception:
                        _log.exception("auto-paper-trade failed for %s -- brain cycle continues", sym)
                elif 0.45 <= confidence < 0.65:
                    _log.info("watch: %s confidence=%.2f", sym, confidence)
                elif confidence < 0.45:
                    _log.debug("low conviction: %s confidence=%.2f", sym, confidence)

        # Fix 4: Auto-close open positions when stop-loss or take-profit is hit.
        # Runs at the end of every brain cycle so paper positions resolve promptly.
        if getattr(self.config.brain, "auto_paper_trade", True):
            _close_log = logging.getLogger("b1e55ed.orchestrator")
            try:
                from engine.execution.pnl import PnLTracker  # local import: avoids circular deps

                pnl_tracker = PnLTracker(self.db, self.config)
                open_positions = self.db.fetchall("SELECT id, asset, direction, stop_loss, take_profit FROM positions WHERE status = 'open'")
                for _pos in open_positions:
                    _pid = str(_pos[0])
                    _asset = str(_pos[1]).upper()
                    _dirn = str(_pos[2]).lower()
                    _stop = float(_pos[3]) if _pos[3] is not None else None
                    _tp = float(_pos[4]) if _pos[4] is not None else None

                    _mark = self._resolve_mid_price(_asset)
                    if _mark is None:
                        continue

                    # Track max_drawdown_during: update each cycle before checking stop/target.
                    try:
                        _dd_row = self.db.fetchone(
                            "SELECT entry_price, max_drawdown_during FROM positions WHERE id = ? AND status = 'open'",
                            (_pid,),
                        )
                        if _dd_row is not None:
                            _entry_px = float(_dd_row[0] or 0.0)
                            _existing_dd = float(_dd_row[1] or 0.0)
                            if _entry_px > 0:
                                if _dirn == "long":
                                    _drawdown = max(0.0, (_entry_px - _mark) / _entry_px)
                                else:  # short
                                    _drawdown = max(0.0, (_mark - _entry_px) / _entry_px)
                                if _drawdown > _existing_dd:
                                    with self.db._lock, self.db.conn:
                                        self.db.execute(
                                            "UPDATE positions SET max_drawdown_during = ? WHERE id = ? AND status = 'open'",
                                            (_drawdown, _pid),
                                        )
                    except Exception:
                        pass  # non-critical; don't disrupt close logic

                    _close_reason: str | None = None
                    if _dirn == "long":
                        if _stop is not None and _mark <= _stop:
                            _close_reason = "stop_loss"
                        elif _tp is not None and _mark >= _tp:
                            _close_reason = "take_profit"
                    elif _dirn == "short":
                        # For shorts: stop is ABOVE entry, take-profit is BELOW entry.
                        if _stop is not None and _mark >= _stop:
                            _close_reason = "stop_loss"
                        elif _tp is not None and _mark <= _tp:
                            _close_reason = "take_profit"

                    if _close_reason:
                        try:
                            pnl_tracker.close_position(position_id=_pid, exit_price=_mark, reason=_close_reason)
                            _close_log.info(
                                "auto-close: position %s (%s %s) closed at %.4f reason=%s",
                                _pid,
                                _dirn,
                                _asset,
                                _mark,
                                _close_reason,
                            )
                        except Exception:
                            _close_log.warning("auto-close failed for position %s", _pid, exc_info=True)
            except Exception:
                _close_log.warning("auto-close cycle check failed", exc_info=True)

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

        # Resolve expired SPI signals
        try:
            from engine.spi.resolution import resolve_expired_signals

            spi_cfg = getattr(self.config, "spi", None)

            # Build chain_client for on-chain karma writes (fail-open)
            _chain_client = None
            _system_agent_id = 0
            try:
                onchain_cfg = getattr(self.config, "onchain", None)
                if (
                    onchain_cfg is not None
                    and getattr(onchain_cfg, "enabled", False)
                    and getattr(onchain_cfg, "rpc_url", "")
                    and getattr(onchain_cfg, "private_key", None)
                ):
                    from engine.oracle.chain import ChainClient  # noqa: PLC0415

                    _chain_client = ChainClient(
                        rpc_url=onchain_cfg.rpc_url,
                        private_key=onchain_cfg.private_key.get_secret_value(),
                        reputation_registry_address=getattr(onchain_cfg, "reputation_registry_address", ""),
                        public_base_url=getattr(onchain_cfg, "public_base_url", ""),
                    )
                    _system_agent_id = getattr(onchain_cfg, "system_agent_id", 0)
            except Exception:
                logging.getLogger("b1e55ed.orchestrator").debug("chain_client init skipped (non-fatal)", exc_info=True)

            spi_outcomes = resolve_expired_signals(
                self.db,
                extra_coingecko=getattr(spi_cfg, "extra_coingecko_symbols", None),
                extra_kraken=getattr(spi_cfg, "extra_kraken_symbols", None),
                chain_client=_chain_client,
                system_agent_id=_system_agent_id,
            )
            if spi_outcomes:
                logging.getLogger("b1e55ed.orchestrator").info(
                    "SPI resolution: %d outcomes (%d resolved, %d expired)",
                    len(spi_outcomes),
                    sum(1 for o in spi_outcomes if o.status == "resolved"),
                    sum(1 for o in spi_outcomes if o.status == "expired"),
                )
        except Exception:
            logging.getLogger("b1e55ed.orchestrator").debug("SPI resolution skipped (non-fatal)", exc_info=True)

        self.hooks.post_cycle(PostCycleContext(config=self.config, db=self.db, cycle_id=cycle_id, result=result))
        return result
