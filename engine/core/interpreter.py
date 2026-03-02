"""engine.core.interpreter

The interpretation seam: converts domain signals into FORECAST_V1 events.

An Interpreter sits between raw producer output and the forecast record.
It answers one question per cycle: given what I observed, what is my call?

Producers that implement interpret() are forecast-capable.
Producers that don't default to abstention (no_forecast).
The seam is additive -- existing producers need no changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from engine.core.events import AbstentionReason, ForecastPayload
from engine.core.forecast import abstain


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
