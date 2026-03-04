from __future__ import annotations

from typing import Any

import pytest

from engine.core.events import AbstentionReason, ForecastPayload
from engine.core.forecast import make_forecast_id
from engine.core.interpreter import Interpreter
from engine.core.regime import RegimeConfig, RegimeMatrix
from engine.producers.tradfi import TradFiBasisInterpreter


class _ConfigurableInterpreter(Interpreter):
    def __init__(self, payload: ForecastPayload, *, regime_matrix: RegimeMatrix | None = None, min_confidence: float = 0.1) -> None:
        self.payload = payload
        self.regime_matrix = regime_matrix
        self.min_confidence = min_confidence

    def interpret(
        self,
        *,
        asset: str,
        horizon: str,
        signals: list[dict[str, Any]],
        regime_tag: str = "unknown",
        visible_signal_refs: list[str] | None = None,
    ) -> ForecastPayload:
        return self.payload.model_copy(deep=True)


def _mk_forecast(*, action: str = "long", confidence: float = 0.8) -> ForecastPayload:
    kwargs: dict[str, Any] = {
        "forecast_id": make_forecast_id(),
        "asset": "BTC",
        "horizon": "4h",
        "action": action,
        "confidence": confidence,
        "source": "unit@1.0.0",
        "regime_tag": "unknown",
        "visible_signal_refs": ["evt-1"],
        "used_signal_refs": ["evt-1"],
    }
    if action == "no_forecast":
        kwargs["confidence"] = 0.0
        kwargs["abstention_reason"] = AbstentionReason.INSUFFICIENT_DATA
    return ForecastPayload(**kwargs)


def test_regime_matrix_get_returns_known_config() -> None:
    cfg = RegimeConfig(confidence_multiplier=0.7, min_confidence=0.5)
    matrix = RegimeMatrix(configs={"BEAR": cfg})

    assert matrix.get("bear") == cfg


def test_regime_matrix_get_returns_default_for_unknown_regime() -> None:
    default = RegimeConfig(confidence_multiplier=0.9)
    matrix = RegimeMatrix(configs={"BULL": RegimeConfig(confidence_multiplier=1.1)}, default=default)

    assert matrix.get("sideways") == default


def test_apply_regime_conditioning_abstains_when_configured() -> None:
    matrix = RegimeMatrix(configs={"CRISIS": RegimeConfig(abstain=True)})
    interpreter = _ConfigurableInterpreter(_mk_forecast(confidence=0.7), regime_matrix=matrix)

    out = interpreter.apply_regime_conditioning(_mk_forecast(confidence=0.7), "CRISIS")

    assert out.action == "no_forecast"
    assert out.abstention_reason == AbstentionReason.REGIME_FILTERED


def test_apply_regime_conditioning_applies_confidence_multiplier() -> None:
    matrix = RegimeMatrix(configs={"BEAR": RegimeConfig(confidence_multiplier=0.5)})
    interpreter = _ConfigurableInterpreter(_mk_forecast(confidence=0.8), regime_matrix=matrix)

    out = interpreter.apply_regime_conditioning(_mk_forecast(confidence=0.8), "BEAR")

    assert out.action == "long"
    assert out.confidence == pytest.approx(0.4)


def test_apply_regime_conditioning_abstains_when_multiplier_drops_below_min_confidence() -> None:
    matrix = RegimeMatrix(configs={"BEAR": RegimeConfig(confidence_multiplier=0.5)})
    interpreter = _ConfigurableInterpreter(_mk_forecast(confidence=0.6), regime_matrix=matrix, min_confidence=0.35)

    out = interpreter.apply_regime_conditioning(_mk_forecast(confidence=0.6), "BEAR")

    assert out.action == "no_forecast"
    assert out.abstention_reason == AbstentionReason.LOW_CONFIDENCE


def test_apply_regime_conditioning_abstains_when_active_rules_empty() -> None:
    matrix = RegimeMatrix(configs={"TRANSITION": RegimeConfig(active_rules=frozenset())})
    interpreter = _ConfigurableInterpreter(_mk_forecast(confidence=0.7), regime_matrix=matrix)

    out = interpreter.apply_regime_conditioning(_mk_forecast(confidence=0.7), "TRANSITION")

    assert out.action == "no_forecast"
    assert out.abstention_reason == AbstentionReason.REGIME_FILTERED


def test_apply_regime_conditioning_passes_through_no_forecast_unchanged() -> None:
    matrix = RegimeMatrix(configs={"BULL": RegimeConfig(confidence_multiplier=1.2)})
    interpreter = _ConfigurableInterpreter(_mk_forecast(action="no_forecast"), regime_matrix=matrix)
    candidate = _mk_forecast(action="no_forecast")

    out = interpreter.apply_regime_conditioning(candidate, "BULL")

    assert out is candidate


def test_apply_regime_conditioning_passes_through_when_no_matrix() -> None:
    interpreter = _ConfigurableInterpreter(_mk_forecast(confidence=0.8), regime_matrix=None)
    candidate = _mk_forecast(confidence=0.8)

    out = interpreter.apply_regime_conditioning(candidate, "BEAR")

    assert out is candidate


def test_safe_interpret_applies_regime_conditioning() -> None:
    matrix = RegimeMatrix(configs={"BEAR": RegimeConfig(confidence_multiplier=0.5)})
    interpreter = _ConfigurableInterpreter(_mk_forecast(confidence=0.8), regime_matrix=matrix)

    out = interpreter.safe_interpret(asset="BTC", horizon="4h", signals=[{"id": "sig-1"}], regime_tag="BEAR")

    assert out.action == "long"
    assert out.confidence == pytest.approx(0.4)


def test_tradfi_basis_interpreter_crisis_regime_abstains() -> None:
    interpreter = TradFiBasisInterpreter()

    assert interpreter.regime_matrix is not None

    out = interpreter.safe_interpret(
        asset="BTC",
        horizon="4h",
        signals=[{"symbol": "BTC", "direction": "long", "confidence": 0.7, "signal_reason": "basis healthy"}],
        regime_tag="CRISIS",
    )

    assert out.action == "no_forecast"
    assert out.abstention_reason == AbstentionReason.REGIME_FILTERED


def test_tradfi_basis_interpreter_bull_regime_boosts_confidence() -> None:
    interpreter = TradFiBasisInterpreter()

    out = interpreter.safe_interpret(
        asset="BTC",
        horizon="4h",
        signals=[{"symbol": "BTC", "direction": "long", "confidence": 0.5, "signal_reason": "basis healthy"}],
        regime_tag="BULL",
    )

    assert out.action == "long"
    assert out.confidence == pytest.approx(0.55)
