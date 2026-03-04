from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
import pytest

from engine.core.events import AbstentionReason, ForecastLifecycleState, ForecastPayload
from engine.core.forecast import make_forecast_id
from engine.core.interpreter import Interpreter, ProsecutorInterpreter, SelfMemoryInterpreter
from engine.core.prosecutor import ProsecutionResult, Prosecutor, ProsecutorConfig
from engine.producers.tradfi import TradFiBasisInterpreter


class _StaticInterpreter(Interpreter):
    producer_name = "unit-producer"
    producer_version = "1.0.0"

    def __init__(self, payload: ForecastPayload) -> None:
        self.payload = payload

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


class _FakeProsecutor:
    def __init__(self, result: ProsecutionResult, *, enabled: bool = True, shadow: bool = False) -> None:
        self.result = result
        self.called = False
        self.config = ProsecutorConfig(enabled=enabled, shadow=shadow)

    def prosecute(
        self,
        *,
        candidate: ForecastPayload,
        signals: list[dict[str, Any]],
        regime_tag: str = "unknown",
    ) -> ProsecutionResult:
        self.called = True
        return self.result


def _mk_payload(*, action: str = "long", confidence: float = 0.6) -> ForecastPayload:
    kwargs: dict[str, Any] = {
        "forecast_id": make_forecast_id(),
        "asset": "BTC",
        "horizon": "4h",
        "action": action,
        "confidence": confidence,
        "source": "unit-producer@1.0.0",
        "regime_tag": "unknown",
        "lifecycle_state": ForecastLifecycleState.NEW,
        "visible_signal_refs": ["evt-1"],
        "used_signal_refs": ["evt-1"],
    }
    if action == "no_forecast":
        kwargs["confidence"] = 0.0
        kwargs["abstention_reason"] = AbstentionReason.INSUFFICIENT_DATA
    return ForecastPayload(**kwargs)


def test_prosecutor_parse_valid_json() -> None:
    raw = '{"bear_strength":0.72,"bull_strength":0.41,"suppress":true,"confidence_boost":0.05,"rationale":"bear case dominates"}'

    result = Prosecutor._parse(raw)

    assert result.error is None
    assert result.bear_strength == pytest.approx(0.72)
    assert result.bull_strength == pytest.approx(0.41)
    assert result.suppress is True
    assert result.confidence_boost == pytest.approx(0.05)
    assert result.rationale == "bear case dominates"


def test_prosecutor_parse_markdown_fenced_json() -> None:
    raw = """```json
    {
      "bear_strength": 0.10,
      "bull_strength": 0.80,
      "suppress": false,
      "confidence_boost": 0.10,
      "rationale": "counter-case is weak"
    }
    ```"""

    result = Prosecutor._parse(raw)

    assert result.error is None
    assert result.suppress is False
    assert result.confidence_boost == pytest.approx(0.10)
    assert result.rationale == "counter-case is weak"


def test_prosecutor_parse_garbage_returns_safe_fallback() -> None:
    result = Prosecutor._parse("definitely not json")

    assert result.error is not None
    assert result.rationale == "parse_error"
    assert result.suppress is False
    assert result.confidence_boost == pytest.approx(0.0)


def test_prosecutor_prosecute_disabled_returns_noop() -> None:
    prosecutor = Prosecutor(ProsecutorConfig(enabled=False))

    result = prosecutor.prosecute(candidate=_mk_payload(), signals=[{"name": "x"}], regime_tag="BULL")

    assert result.suppress is False
    assert result.confidence_boost == pytest.approx(0.0)
    assert result.rationale == "prosecutor_disabled"


def test_prosecutor_prosecute_httpx_error_returns_safe_result() -> None:
    prosecutor = Prosecutor(ProsecutorConfig(enabled=True, key="test-key"))

    with patch("engine.core.prosecutor.httpx.Client", side_effect=httpx.TimeoutException("boom")):
        result = prosecutor.prosecute(candidate=_mk_payload(), signals=[{"name": "x"}], regime_tag="BULL")

    assert result.suppress is False
    assert result.confidence_boost == pytest.approx(0.0)
    assert result.rationale == "prosecutor_error"
    assert result.error is not None


def test_prosecutor_config_from_env_reads_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("B1E55ED_PROSECUTOR_ENABLED", "true")
    monkeypatch.setenv("B1E55ED_PROSECUTOR_URL", "https://llm.example/v1")
    monkeypatch.setenv("B1E55ED_PROSECUTOR_MODEL", "test-model")
    monkeypatch.setenv("B1E55ED_PROSECUTOR_TIMEOUT_S", "3.25")
    monkeypatch.setenv("B1E55ED_PROSECUTOR_SHADOW", "false")
    monkeypatch.delenv("B1E55ED_PROSECUTOR_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "fallback-key")

    cfg = ProsecutorConfig.from_env()

    assert cfg.enabled is True
    assert cfg.url == "https://llm.example/v1"
    assert cfg.key == "fallback-key"
    assert cfg.model == "test-model"
    assert cfg.timeout_s == pytest.approx(3.25)
    assert cfg.shadow is False


def test_prosecutor_interpreter_without_prosecutor_passes_through() -> None:
    candidate = _mk_payload(action="long", confidence=0.61)
    wrapped = ProsecutorInterpreter(inner=_StaticInterpreter(candidate), prosecutor=None, shadow=False)

    out = wrapped.interpret(asset="BTC", horizon="4h", signals=[], regime_tag="BULL")

    assert out.action == candidate.action
    assert out.confidence == pytest.approx(candidate.confidence)


def test_prosecutor_interpreter_shadow_mode_does_not_suppress() -> None:
    candidate = _mk_payload(action="long", confidence=0.62)
    fake = _FakeProsecutor(
        ProsecutionResult(
            bear_strength=0.85,
            bull_strength=0.35,
            suppress=True,
            confidence_boost=0.0,
            rationale="strong bear case",
            raw_response="{}",
        ),
        enabled=True,
        shadow=False,
    )
    wrapped = ProsecutorInterpreter(inner=_StaticInterpreter(candidate), prosecutor=fake, shadow=True)

    out = wrapped.interpret(asset="BTC", horizon="4h", signals=[], regime_tag="BULL")

    assert fake.called is True
    assert out.action == candidate.action
    assert out.confidence == pytest.approx(candidate.confidence)


def test_prosecutor_interpreter_live_mode_suppresses_to_abstention() -> None:
    candidate = _mk_payload(action="long", confidence=0.62)
    fake = _FakeProsecutor(
        ProsecutionResult(
            bear_strength=0.80,
            bull_strength=0.40,
            suppress=True,
            confidence_boost=0.0,
            rationale="counter-thesis stronger",
            raw_response="{}",
        ),
        enabled=True,
        shadow=False,
    )
    wrapped = ProsecutorInterpreter(inner=_StaticInterpreter(candidate), prosecutor=fake, shadow=False)

    out = wrapped.interpret(asset="BTC", horizon="4h", signals=[], regime_tag="BULL")

    assert out.action == "no_forecast"
    assert out.abstention_reason == AbstentionReason.LOW_CONFIDENCE


def test_prosecutor_interpreter_live_mode_applies_confidence_boost() -> None:
    candidate = _mk_payload(action="long", confidence=0.60)
    fake = _FakeProsecutor(
        ProsecutionResult(
            bear_strength=0.20,
            bull_strength=0.70,
            suppress=False,
            confidence_boost=0.10,
            rationale="weak bear case",
            raw_response="{}",
        ),
        enabled=True,
        shadow=False,
    )
    wrapped = ProsecutorInterpreter(inner=_StaticInterpreter(candidate), prosecutor=fake, shadow=False)

    out = wrapped.interpret(asset="BTC", horizon="4h", signals=[], regime_tag="BULL")

    assert out.action == "long"
    assert out.confidence == pytest.approx(0.70)


def test_prosecutor_interpreter_live_mode_boost_respects_regime_cap() -> None:
    candidate = _mk_payload(action="long", confidence=0.68)
    fake = _FakeProsecutor(
        ProsecutionResult(
            bear_strength=0.15,
            bull_strength=0.80,
            suppress=False,
            confidence_boost=0.10,
            rationale="weak bear case",
            raw_response="{}",
        ),
        enabled=True,
        shadow=False,
    )
    wrapped = ProsecutorInterpreter(inner=_StaticInterpreter(candidate), prosecutor=fake, shadow=False)

    out = wrapped.interpret(asset="BTC", horizon="4h", signals=[], regime_tag="BEAR")

    assert out.action == "long"
    assert out.confidence == pytest.approx(0.70)


def test_prosecutor_interpreter_no_forecast_passes_through_without_prosecution() -> None:
    candidate = _mk_payload(action="no_forecast")
    fake = _FakeProsecutor(
        ProsecutionResult(
            bear_strength=1.0,
            bull_strength=0.0,
            suppress=True,
            confidence_boost=0.0,
            rationale="irrelevant",
            raw_response="{}",
        ),
        enabled=True,
        shadow=False,
    )
    wrapped = ProsecutorInterpreter(inner=_StaticInterpreter(candidate), prosecutor=fake, shadow=False)

    out = wrapped.interpret(asset="BTC", horizon="4h", signals=[], regime_tag="BULL")

    assert out.action == "no_forecast"
    assert fake.called is False


def test_full_stack_prosecutor_over_self_memory_over_tradfi_composes() -> None:
    stack = ProsecutorInterpreter(
        inner=SelfMemoryInterpreter(inner=TradFiBasisInterpreter(), db=None),
        prosecutor=None,
        shadow=False,
    )
    stack.producer_name = "tradfi-basis"
    stack.producer_version = "1.0.0"

    out = stack.interpret(
        asset="BTC",
        horizon="4h",
        signals=[
            {
                "symbol": "BTC",
                "direction": "long",
                "confidence": 0.75,
                "signal_reason": "carry edge",
                "liq_asymmetry": 0.50,
            }
        ],
        regime_tag="BULL",
        visible_signal_refs=["evt-1"],
    )

    assert out.action == "long"
    assert out.source == "tradfi-basis@1.0.0"
    assert out.confidence > 0.75
    assert out.visible_signal_refs == ["evt-1"]
