from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from engine.core.events import AbstentionReason, ForecastLifecycleState, ForecastPayload
from engine.core.forecast import make_forecast_id
from engine.core.interpreter import Interpreter, LLMCriticInterpreter, NullInterpreter
from engine.core.llm_critic import CritiqueResult, LLMCritic, LLMCriticConfig


class _StaticInterpreter(Interpreter):
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


class _StubCritic:
    def __init__(self, result: CritiqueResult, *, enabled: bool = True) -> None:
        self.result = result
        self.config = LLMCriticConfig(enabled=enabled, key="test-key")
        self.called = 0

    def critique(
        self,
        *,
        candidate: ForecastPayload,
        signals: list[dict],
        regime_tag: str,
        trailing_brier: float | None,
        aggregate_conviction: float | None,
    ) -> CritiqueResult:
        self.called += 1
        return self.result


def _mk_payload(*, action: str = "long", confidence: float = 0.6, reasoning_hash: str | None = None) -> ForecastPayload:
    kwargs: dict[str, Any] = {
        "forecast_id": make_forecast_id(),
        "asset": "BTC",
        "horizon": "4h",
        "action": action,
        "confidence": confidence,
        "source": "unit@1.0.0",
        "regime_tag": "unknown",
        "lifecycle_state": ForecastLifecycleState.NEW,
        "visible_signal_refs": ["evt-1"],
        "used_signal_refs": ["evt-1"],
    }
    if reasoning_hash is not None:
        kwargs["reasoning_hash"] = reasoning_hash
    if action == "no_forecast":
        kwargs["confidence"] = 0.0
        kwargs["abstention_reason"] = AbstentionReason.INSUFFICIENT_DATA
    return ForecastPayload(**kwargs)


def _mock_client_with_content(content: str) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"choices": [{"message": {"content": content}}]}

    client = MagicMock()
    client.post.return_value = response
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    return client


def test_llm_critic_happy_path_parses_json_and_clamps_delta() -> None:
    critic = LLMCritic(LLMCriticConfig(enabled=True, key="sk-test"))
    client = _mock_client_with_content('{"confidence_delta": 0.45, "suppress": false, "rationale": "trim confidence"}')

    with patch("engine.core.llm_critic.httpx.Client", return_value=client):
        result = critic.critique(
            candidate=_mk_payload(),
            signals=[{"name": "basis", "value": 5.1}],
            regime_tag="BULL",
            trailing_brier=0.22,
            aggregate_conviction=0.71,
        )

    assert result.error is None
    assert result.confidence_delta == pytest.approx(0.3)
    assert result.suppress is False
    assert result.rationale == "trim confidence"
    assert result.raw_response
    assert client.post.call_args.args[0] == "/chat/completions"


def test_llm_critic_parse_error_falls_back_to_neutral_result() -> None:
    critic = LLMCritic(LLMCriticConfig(enabled=True, key="sk-test"))
    client = _mock_client_with_content("not-json")

    with patch("engine.core.llm_critic.httpx.Client", return_value=client):
        result = critic.critique(
            candidate=_mk_payload(),
            signals=[],
            regime_tag="BULL",
            trailing_brier=None,
            aggregate_conviction=None,
        )

    assert result.confidence_delta == 0.0
    assert result.suppress is False
    assert result.rationale == ""
    assert result.raw_response == ""
    assert result.error is not None


def test_llm_critic_timeout_falls_back_to_neutral_result() -> None:
    critic = LLMCritic(LLMCriticConfig(enabled=True, key="sk-test"))

    client = MagicMock()
    client.post.side_effect = httpx.TimeoutException("timeout")
    client.__enter__.return_value = client
    client.__exit__.return_value = False

    with patch("engine.core.llm_critic.httpx.Client", return_value=client):
        result = critic.critique(
            candidate=_mk_payload(),
            signals=[],
            regime_tag="BULL",
            trailing_brier=None,
            aggregate_conviction=None,
        )

    assert result.confidence_delta == 0.0
    assert result.suppress is False
    assert result.raw_response == ""
    assert result.error is not None


def test_llm_critic_interpreter_shadow_mode_returns_rule_output_and_sets_reasoning_hash() -> None:
    candidate = _mk_payload(action="long", confidence=0.62, reasoning_hash=None)
    inner = _StaticInterpreter(candidate)
    critic = _StubCritic(
        CritiqueResult(
            confidence_delta=-0.1,
            suppress=False,
            rationale="confidence too high in chop",
            raw_response='{"confidence_delta": -0.1, "suppress": false, "rationale": "confidence too high in chop"}',
        )
    )

    wrapped = LLMCriticInterpreter(inner=inner, critic=critic, shadow=True)
    out = wrapped.interpret(asset="BTC", horizon="4h", signals=[{"name": "basis", "value": 4.1}], regime_tag="BULL")

    assert out.action == "long"
    assert out.confidence == pytest.approx(0.62)
    assert out.reasoning_hash is not None
    assert critic.called == 1


def test_llm_critic_interpreter_live_mode_adjusts_confidence_without_changing_action() -> None:
    candidate = _mk_payload(action="long", confidence=0.6)
    inner = _StaticInterpreter(candidate)
    critic = _StubCritic(CritiqueResult(confidence_delta=0.1, suppress=False, rationale="slightly stronger", raw_response='{"confidence_delta":0.1}'))

    wrapped = LLMCriticInterpreter(inner=inner, critic=critic, shadow=False)
    out = wrapped.interpret(asset="BTC", horizon="4h", signals=[], regime_tag="BULL")

    assert out.action == "long"
    assert out.confidence == pytest.approx(0.7)


def test_llm_critic_interpreter_live_mode_suppresses_to_abstention() -> None:
    candidate = _mk_payload(action="short", confidence=0.75)
    inner = _StaticInterpreter(candidate)
    critic = _StubCritic(CritiqueResult(confidence_delta=0.0, suppress=True, rationale="suppress", raw_response='{"suppress":true}'))

    wrapped = LLMCriticInterpreter(inner=inner, critic=critic, shadow=False)
    out = wrapped.interpret(asset="BTC", horizon="4h", signals=[], regime_tag="BULL")

    assert out.action == "no_forecast"
    assert out.abstention_reason == AbstentionReason.LOW_CONFIDENCE


def test_llm_critic_interpreter_live_mode_applies_regime_cap() -> None:
    candidate = _mk_payload(action="long", confidence=0.6)
    inner = _StaticInterpreter(candidate)
    critic = _StubCritic(CritiqueResult(confidence_delta=0.3, suppress=False, rationale="up", raw_response='{"confidence_delta":0.3}'))

    wrapped = LLMCriticInterpreter(inner=inner, critic=critic, shadow=False)
    out = wrapped.interpret(asset="BTC", horizon="4h", signals=[], regime_tag="BEAR")

    assert out.action == "long"
    assert out.confidence == pytest.approx(0.7)


def test_llm_critic_interpreter_no_forecast_passes_through_without_critique_call() -> None:
    candidate = _mk_payload(action="no_forecast")
    inner = _StaticInterpreter(candidate)
    critic = _StubCritic(CritiqueResult(confidence_delta=0.2, suppress=False, rationale="", raw_response=""))

    wrapped = LLMCriticInterpreter(inner=inner, critic=critic, shadow=False)
    out = wrapped.interpret(asset="BTC", horizon="4h", signals=[], regime_tag="BULL")

    assert out.action == "no_forecast"
    assert critic.called == 0


def test_llm_critic_interpreter_llm_error_returns_rule_output_unmodified() -> None:
    candidate = _mk_payload(action="long", confidence=0.58, reasoning_hash=None)
    inner = _StaticInterpreter(candidate)
    critic = _StubCritic(CritiqueResult(confidence_delta=0.0, suppress=False, rationale="", raw_response="", error="boom"))

    wrapped = LLMCriticInterpreter(inner=inner, critic=critic, shadow=False)
    out = wrapped.interpret(asset="BTC", horizon="4h", signals=[], regime_tag="BULL")

    assert out.action == candidate.action
    assert out.confidence == pytest.approx(candidate.confidence)
    assert out.reasoning_hash == candidate.reasoning_hash


def test_null_interpreter_wrapped_with_llm_critic_still_abstains() -> None:
    critic = _StubCritic(CritiqueResult(confidence_delta=0.2, suppress=False, rationale="", raw_response=""))
    wrapped = LLMCriticInterpreter(inner=NullInterpreter(), critic=critic, shadow=False)

    out = wrapped.interpret(asset="BTC", horizon="4h", signals=[], regime_tag="BULL")

    assert out.action == "no_forecast"
    assert out.abstention_reason == AbstentionReason.INSUFFICIENT_DATA
    assert critic.called == 0
