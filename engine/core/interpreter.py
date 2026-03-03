"""engine.core.interpreter

The interpretation seam: converts domain signals into FORECAST_V1 events.

An Interpreter sits between raw producer output and the forecast record.
It answers one question per cycle: given what I observed, what is my call?

Producers that implement interpret() are forecast-capable.
Producers that don't default to abstention (no_forecast).
The seam is additive -- existing producers need no changes.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from engine.brain.conviction_state import ConvictionStateReader
from engine.core.events import AbstentionReason, ForecastPayload
from engine.core.forecast import abstain, compute_reasoning_hash
from engine.core.llm_critic import LLMCritic
from engine.core.novelty import NOVELTY_MIN_CONFIDENCE, NoveltyResult, compute_novelty_penalty
from engine.core.prosecutor import ProsecutionResult, Prosecutor
from engine.core.regime import REGIME_CAPS as _REGIME_CAPS
from engine.core.regime import RegimeMatrix
from engine.core.self_memory import SelfMemory, SelfMemoryConfig
from engine.core.utils import clamp

logger = logging.getLogger(__name__)


# Shannon's channel capacity theorem: every noisy channel has a maximum reliable throughput.
# Below the noise floor, transmission fails. interpret() is the channel. abstain() is that floor.
class Interpreter(ABC):
    """Abstract base for producer-level forecast interpretation.

    One Interpreter per producer. Converts the producer's domain
    signals into a structured ForecastPayload each cycle.

    Subclasses implement interpret(). The default fallback is abstention.
    """

    #: Set by the concrete producer. Used for source field in ForecastPayload.
    producer_name: str = "unknown"
    producer_version: str = "0.0.0"

    @property
    def source(self) -> str:
        return f"{self.producer_name}@{self.producer_version}"

    # Declare a RegimeMatrix on a subclass to enable regime-conditioned output.
    # None means "pass interpret() output through unchanged".
    regime_matrix: RegimeMatrix | None = None

    # Default minimum confidence for non-abstention.
    # Overridden by RegimeConfig.min_confidence.
    min_confidence: float = 0.1

    def apply_regime_conditioning(
        self,
        forecast: ForecastPayload,
        regime_tag: str,
    ) -> ForecastPayload:
        """Apply regime matrix to a candidate forecast.

        Called automatically by safe_interpret(). Subclasses should NOT call
        this themselves — it is applied once at the seam.

        Returns the forecast unchanged if:
        - no regime_matrix is set
        - forecast.action == "no_forecast"
        - RegimeConfig has no-op values (multiplier=1.0, abstain=False)
        """
        from engine.core.utils import clamp  # local import to avoid circular at module load

        if self.regime_matrix is None or forecast.action == "no_forecast":
            return forecast

        cfg = self.regime_matrix.get(regime_tag)

        # Hard abstain for this regime
        if cfg.abstain:
            return abstain(
                source=forecast.source,
                asset=forecast.asset,
                horizon=forecast.horizon,
                reason=AbstentionReason.REGIME_FILTERED,
                regime_tag=regime_tag,
                visible_signal_refs=forecast.visible_signal_refs,
            )

        # active_rules=frozenset() means no rules run — implicit abstain
        if cfg.active_rules is not None and len(cfg.active_rules) == 0:
            return abstain(
                source=forecast.source,
                asset=forecast.asset,
                horizon=forecast.horizon,
                reason=AbstentionReason.REGIME_FILTERED,
                regime_tag=regime_tag,
                visible_signal_refs=forecast.visible_signal_refs,
            )

        # Apply confidence multiplier
        new_confidence = clamp(forecast.confidence * cfg.confidence_multiplier, 0.0, 1.0)

        # Apply min_confidence (regime-specific override, else use class default)
        effective_min = cfg.min_confidence if cfg.min_confidence is not None else self.min_confidence
        if new_confidence < effective_min:
            return abstain(
                source=forecast.source,
                asset=forecast.asset,
                horizon=forecast.horizon,
                reason=AbstentionReason.LOW_CONFIDENCE,
                regime_tag=regime_tag,
                visible_signal_refs=forecast.visible_signal_refs,
            )

        if new_confidence == forecast.confidence:
            return forecast  # no change, avoid unnecessary copy

        return forecast.model_copy(update={"confidence": new_confidence})

    @abstractmethod
    def interpret(
        self,
        *,
        asset: str,
        horizon: str,
        signals: list[dict[str, Any]],
        regime_tag: str = "unknown",
        visible_signal_refs: list[str] | None = None,
    ) -> ForecastPayload:
        """Produce a ForecastPayload from the current cycle's signals.

        Args:
            asset: The asset symbol being forecasted (e.g. "BTC").
            horizon: Forecast horizon string (e.g. "4h", "24h").
            signals: Raw signal dicts from this producer's collect/normalize cycle.
            regime_tag: Current regime label from the brain (risk-on/risk-off/chop/unknown).
            visible_signal_refs: Event IDs of all events in the lookback window.

        Returns:
            A ForecastPayload. Return abstain() when there is no confident call.
        """
        ...

    def safe_interpret(
        self,
        *,
        asset: str,
        horizon: str,
        signals: list[dict[str, Any]],
        regime_tag: str = "unknown",
        visible_signal_refs: list[str] | None = None,
        default_reason: AbstentionReason = AbstentionReason.INSUFFICIENT_DATA,
    ) -> ForecastPayload:
        """Call interpret() and fall back to abstention on any exception."""
        try:
            result = self.interpret(
                asset=asset,
                horizon=horizon,
                signals=signals,
                regime_tag=regime_tag,
                visible_signal_refs=visible_signal_refs,
            )
            return self.apply_regime_conditioning(result, regime_tag)
        except Exception:  # noqa: BLE001
            return abstain(
                source=self.source,
                asset=asset,
                horizon=horizon,
                reason=default_reason,
                regime_tag=regime_tag,
                visible_signal_refs=visible_signal_refs or [],
            )


# Cromwell's Rule: never assign probability zero or one to any hypothesis.
# NullInterpreter holds maximum uncertainty -- the correct prior when evidence is absent.
class NullInterpreter(Interpreter):
    """Always abstains. Default for producers that have no interpretation logic yet.

    Using NullInterpreter explicitly is better than omitting interpreter entirely --
    it signals that the producer is forecast-aware but not yet forecast-capable.
    """

    def interpret(
        self,
        *,
        asset: str,
        horizon: str,
        signals: list[dict[str, Any]],
        regime_tag: str = "unknown",
        visible_signal_refs: list[str] | None = None,
    ) -> ForecastPayload:
        return abstain(
            source=self.source,
            asset=asset,
            horizon=horizon,
            reason=AbstentionReason.INSUFFICIENT_DATA,
            regime_tag=regime_tag,
            visible_signal_refs=visible_signal_refs or [],
        )


class LLMCriticInterpreter(Interpreter):
    """Wraps any Interpreter with an optional LLM critic pass.

    In shadow mode (default): rule-based output is returned, LLM critique
    is computed and stored in reasoning_hash but does not affect the output.

    In live mode: LLM critique modifies confidence within guardrails.
    Action (long/short/flat) is NEVER changed by the LLM.

    Degrades gracefully: if LLM is unconfigured or errors, behaves like
    the wrapped interpreter.
    """

    def __init__(
        self,
        inner: Interpreter,
        critic: LLMCritic | None = None,
        shadow: bool = True,
        db: Any | None = None,
        trailing_brier_fn: Callable[[str], float | None] | None = None,
        aggregate_conviction_fn: Callable[[str], float | None] | None = None,
        regime_caps: dict[str, float] | None = None,
        min_live_confidence: float = 0.3,
    ) -> None:
        self.inner = inner
        self.critic = critic
        self.shadow = shadow
        self.db = db
        self.trailing_brier_fn = trailing_brier_fn
        self.aggregate_conviction_fn = aggregate_conviction_fn
        self._regime_caps: dict[str, float] = regime_caps if regime_caps is not None else _REGIME_CAPS
        self.min_live_confidence = min_live_confidence

    @staticmethod
    def _with_reasoning_hash(payload: ForecastPayload, *, critique: str, rationale: str) -> ForecastPayload:
        candidate = payload.model_dump(mode="json")
        candidate["reasoning_hash"] = None
        reasoning_hash = compute_reasoning_hash(candidate=candidate, critique=critique, rationale=rationale)
        return payload.model_copy(update={"reasoning_hash": reasoning_hash})

    def _producer_name_for_logging(self, candidate: ForecastPayload) -> str:
        if self.producer_name and self.producer_name != "unknown":
            return self.producer_name
        inner_name = getattr(self.inner, "producer_name", "")
        if inner_name:
            return str(inner_name)
        src = str(candidate.source)
        return src.split("@", 1)[0] if "@" in src else src

    def _resolve_trailing_brier(self) -> float | None:
        if self.trailing_brier_fn is None:
            return None
        try:
            producer_name = self.producer_name if self.producer_name else getattr(self.inner, "producer_name", "unknown")
            return self.trailing_brier_fn(str(producer_name))
        except Exception:  # noqa: BLE001
            logger.warning("llm_critic_trailing_brier_failed")
            return None

    def _resolve_aggregate_conviction(self, asset: str) -> float | None:
        if self.aggregate_conviction_fn is None:
            return None
        try:
            return self.aggregate_conviction_fn(asset)
        except Exception:  # noqa: BLE001
            logger.warning("llm_critic_aggregate_conviction_failed")
            return None

    def _log_shadow(
        self,
        *,
        candidate: ForecastPayload,
        regime_tag: str,
        result_confidence_delta: float,
        result_suppressed: bool,
        result_rationale: str,
        result_error: str | None,
        shadow_mode: bool,
    ) -> None:
        if self.db is None:
            return
        try:
            from engine.brain.calibration import log_shadow_critique

            log_shadow_critique(
                db=self.db,
                producer=self._producer_name_for_logging(candidate),
                asset=candidate.asset,
                horizon=candidate.horizon,
                regime=regime_tag,
                rule_confidence=float(candidate.confidence),
                llm_confidence_delta=float(result_confidence_delta),
                llm_suppressed=bool(result_suppressed),
                llm_rationale=result_rationale,
                llm_error=result_error,
                shadow_mode=shadow_mode,
            )
        except Exception:  # noqa: BLE001
            logger.warning("llm_critic_shadow_log_failed")

    def interpret(
        self,
        *,
        asset: str,
        horizon: str,
        signals: list[dict[str, Any]],
        regime_tag: str = "unknown",
        visible_signal_refs: list[str] | None = None,
    ) -> ForecastPayload:
        # Keep source wiring aligned with BaseProducer.emit_forecast().
        self.inner.producer_name = self.producer_name
        self.inner.producer_version = self.producer_version

        candidate = self.inner.interpret(
            asset=asset,
            horizon=horizon,
            signals=signals,
            regime_tag=regime_tag,
            visible_signal_refs=visible_signal_refs,
        )

        if candidate.action == "no_forecast":
            return candidate

        if self.critic is None or not self.critic.config.enabled:
            return self._with_reasoning_hash(candidate, critique="", rationale="")

        trailing_brier = self._resolve_trailing_brier()
        aggregate_conviction = self._resolve_aggregate_conviction(asset)

        # Meta-guardrail: if producer's recent Brier is poor, revert to shadow for this cycle.
        effective_shadow = self.shadow
        if not effective_shadow and trailing_brier is not None and trailing_brier > 0.35:
            logger.warning(
                "llm_critic_brier_guardrail: producer=%s trailing_brier=%.4f",
                self.inner.producer_name,
                trailing_brier,
            )
            effective_shadow = True

        result = self.critic.critique(
            candidate=candidate,
            signals=signals,
            regime_tag=regime_tag,
            trailing_brier=trailing_brier,
            aggregate_conviction=aggregate_conviction,
        )

        if result.error:
            logger.warning("llm_critic_failed: %s", result.error)
            return candidate

        bounded_delta = clamp(result.confidence_delta, -0.3, 0.3)

        if effective_shadow:
            self._log_shadow(
                candidate=candidate,
                regime_tag=regime_tag,
                result_confidence_delta=bounded_delta,
                result_suppressed=result.suppress,
                result_rationale=result.rationale,
                result_error=result.error,
                shadow_mode=effective_shadow,
            )
            return self._with_reasoning_hash(candidate, critique=result.raw_response, rationale=result.rationale)

        if result.suppress:
            return abstain(
                source=candidate.source,
                asset=asset,
                horizon=horizon,
                reason=AbstentionReason.LOW_CONFIDENCE,
                regime_tag=regime_tag,
                visible_signal_refs=visible_signal_refs or [],
            )

        new_confidence = clamp(float(candidate.confidence) + bounded_delta, 0.0, 1.0)
        regime_cap = clamp(float(self._regime_caps.get(regime_tag.upper(), 10.0)) / 10.0, 0.0, 1.0)
        new_confidence = min(new_confidence, regime_cap)

        if new_confidence < self.min_live_confidence:
            return abstain(
                source=candidate.source,
                asset=asset,
                horizon=horizon,
                reason=AbstentionReason.LOW_CONFIDENCE,
                regime_tag=regime_tag,
                visible_signal_refs=visible_signal_refs or [],
            )

        updated = candidate.model_copy(update={"confidence": new_confidence})
        return self._with_reasoning_hash(updated, critique=result.raw_response, rationale=result.rationale)


class SelfMemoryInterpreter(Interpreter):
    """Wrap an Interpreter and apply producer self-memory confidence deltas.

    Self-memory is a bounded, pre-emit confidence modulation based on the
    producer's own resolved forecast history.

    Guardrails:
    - no-op when DB is unavailable
    - no-op when insufficient resolved samples
    - confidence delta clamped by SelfMemoryConfig.max_delta
    - action never changes (confidence only)
    """

    def __init__(
        self,
        inner: Interpreter,
        db: Any | None = None,
        config: SelfMemoryConfig | None = None,
    ) -> None:
        self.inner = inner
        self.db = db
        self._self_memory = SelfMemory(db, config) if db is not None else None

        # Mirror identity at init; producer wiring may update self.* later.
        self.producer_name = inner.producer_name
        self.producer_version = inner.producer_version

    def interpret(
        self,
        *,
        asset: str,
        horizon: str,
        signals: list[dict[str, Any]],
        regime_tag: str = "unknown",
        visible_signal_refs: list[str] | None = None,
    ) -> ForecastPayload:
        # Keep source identity aligned with BaseProducer.emit_forecast() wiring.
        self.inner.producer_name = self.producer_name
        self.inner.producer_version = self.producer_version

        candidate = self.inner.safe_interpret(
            asset=asset,
            horizon=horizon,
            signals=signals,
            regime_tag=regime_tag,
            visible_signal_refs=visible_signal_refs,
        )

        if candidate.action == "no_forecast" or self._self_memory is None:
            return candidate

        result = self._self_memory.query(
            producer_name=self.producer_name,
            asset=asset,
            regime=regime_tag,
        )

        if not result.applied:
            logger.debug(
                "self_memory_skipped: producer=%s reason=%s",
                self.producer_name,
                result.skip_reason or result.reason,
            )
            return candidate

        new_confidence = clamp(float(candidate.confidence) + float(result.confidence_delta), 0.0, 1.0)

        logger.info(
            "self_memory_applied: producer=%s asset=%s original=%.4f delta=%+.4f new=%.4f long_brier=%s recent_brier=%s",
            self.producer_name,
            asset,
            float(candidate.confidence),
            float(result.confidence_delta),
            float(new_confidence),
            result.long_term_brier,
            result.recent_brier,
        )

        return candidate.model_copy(update={"confidence": round(new_confidence, 4)})


class ProsecutorInterpreter(Interpreter):
    """Wrap an Interpreter and run an adversarial prosecutor pass post-emit.

    The prosecutor constructs the strongest counter-case against a candidate.
    - suppress=True (and not shadow): abstain
    - confidence_boost>0 (and not shadow): apply bounded confidence boost
    - shadow=True (default): log only, never mutates candidate

    Position in stack: last gate before emission.
    """

    def __init__(
        self,
        inner: Interpreter,
        prosecutor: Prosecutor | None = None,
        shadow: bool = True,
        regime_caps: dict[str, float] | None = None,
    ) -> None:
        self.inner = inner
        self.prosecutor = prosecutor
        self.shadow = shadow
        self._regime_caps: dict[str, float] = regime_caps if regime_caps is not None else _REGIME_CAPS

        # Mirror identity at init; producer wiring may update self.* later.
        self.producer_name = inner.producer_name
        self.producer_version = inner.producer_version

    def interpret(
        self,
        *,
        asset: str,
        horizon: str,
        signals: list[dict[str, Any]],
        regime_tag: str = "unknown",
        visible_signal_refs: list[str] | None = None,
    ) -> ForecastPayload:
        # Keep source identity aligned with BaseProducer.emit_forecast() wiring.
        self.inner.producer_name = self.producer_name
        self.inner.producer_version = self.producer_version

        candidate = self.inner.safe_interpret(
            asset=asset,
            horizon=horizon,
            signals=signals,
            regime_tag=regime_tag,
            visible_signal_refs=visible_signal_refs,
        )

        # Pass through abstentions or when prosecutor is unconfigured.
        if candidate.action == "no_forecast" or self.prosecutor is None:
            return candidate

        result: ProsecutionResult = self.prosecutor.prosecute(
            candidate=candidate,
            signals=signals,
            regime_tag=regime_tag,
        )

        if result.error:
            logger.warning("prosecutor_failed: %s", result.error)
            return candidate

        effective_shadow = self.shadow or self.prosecutor.config.shadow

        logger.info(
            "prosecutor_result: producer=%s asset=%s action=%s confidence=%.4f "
            "bear_strength=%.4f bull_strength=%.4f suppress=%s confidence_boost=%.4f shadow=%s rationale=%s",
            self.producer_name,
            asset,
            candidate.action,
            float(candidate.confidence),
            float(result.bear_strength),
            float(result.bull_strength),
            result.suppress,
            float(result.confidence_boost),
            effective_shadow,
            result.rationale,
        )

        if effective_shadow:
            return candidate

        if result.suppress:
            return abstain(
                source=candidate.source,
                asset=asset,
                horizon=horizon,
                reason=AbstentionReason.LOW_CONFIDENCE,
                regime_tag=regime_tag,
                visible_signal_refs=candidate.visible_signal_refs,
            )

        if result.confidence_boost > 0:
            new_confidence = clamp(float(candidate.confidence) + float(result.confidence_boost), 0.0, 1.0)
            regime_cap = clamp(float(self._regime_caps.get(regime_tag.upper(), 10.0)) / 10.0, 0.0, 1.0)
            new_confidence = min(new_confidence, regime_cap)
            if new_confidence != candidate.confidence:
                return candidate.model_copy(update={"confidence": round(new_confidence, 4)})

        return candidate


class NoveltyInterpreter(Interpreter):
    """Wraps an Interpreter and applies a novelty penalty from aggregate conviction.

    The producer sees only one number per asset: aggregate signed conviction.
    No producer identities, no domain breakdown.

    - High agreement with strong conviction -> suppress confidence (low novelty)
    - Contrarian signal -> slight confidence boost
    - shadow=True (default): observe only, do not mutate
    - db=None: pass-through

    Position in stack: last gate (after Prosecutor) or standalone.
    """

    def __init__(
        self,
        inner: Interpreter,
        db: Any | None = None,
        shadow: bool = True,
        lookback_minutes: int = 120,
    ) -> None:
        self.inner = inner
        self.shadow = shadow
        self._reader = ConvictionStateReader(db, lookback_minutes=lookback_minutes) if db is not None else None

        # Mirror identity at init; producer wiring may update self.* later.
        self.producer_name = inner.producer_name
        self.producer_version = inner.producer_version

    def interpret(
        self,
        *,
        asset: str,
        horizon: str,
        signals: list[dict[str, Any]],
        regime_tag: str = "unknown",
        visible_signal_refs: list[str] | None = None,
    ) -> ForecastPayload:
        # Keep source identity aligned with BaseProducer.emit_forecast() wiring.
        self.inner.producer_name = self.producer_name
        self.inner.producer_version = self.producer_version

        candidate = self.inner.safe_interpret(
            asset=asset,
            horizon=horizon,
            signals=signals,
            regime_tag=regime_tag,
            visible_signal_refs=visible_signal_refs,
        )

        if candidate.action == "no_forecast" or self._reader is None:
            return candidate

        state = self._reader.get(asset)
        result: NoveltyResult = compute_novelty_penalty(
            candidate_action=candidate.action,
            candidate_confidence=float(candidate.confidence),
            brain_conviction=float(state.conviction),
        )

        logger.info(
            "novelty_result: producer=%s asset=%s action=%s confidence=%.4f "
            "brain_conviction=%.4f forecast_count=%d agreement=%.4f delta=%+.4f applied=%s shadow=%s reason=%s",
            self.producer_name,
            asset,
            candidate.action,
            float(candidate.confidence),
            float(state.conviction),
            int(state.forecast_count),
            float(result.agreement),
            float(result.confidence_delta),
            result.applied,
            self.shadow,
            result.reason,
        )

        if self.shadow or not result.applied:
            return candidate

        new_confidence = clamp(float(candidate.confidence) + float(result.confidence_delta), NOVELTY_MIN_CONFIDENCE, 1.0)
        if new_confidence < 0.15:
            return abstain(
                source=candidate.source,
                asset=asset,
                horizon=horizon,
                reason=AbstentionReason.LOW_CONFIDENCE,
                regime_tag=regime_tag,
                visible_signal_refs=candidate.visible_signal_refs,
            )

        return candidate.model_copy(update={"confidence": round(new_confidence, 4)})
