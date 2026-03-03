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

from engine.core.events import AbstentionReason, ForecastPayload
from engine.core.forecast import abstain, compute_reasoning_hash
from engine.core.llm_critic import LLMCritic
from engine.core.regime import REGIME_CAPS as _REGIME_CAPS
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
            return self.interpret(
                asset=asset,
                horizon=horizon,
                signals=signals,
                regime_tag=regime_tag,
                visible_signal_refs=visible_signal_refs,
            )
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
