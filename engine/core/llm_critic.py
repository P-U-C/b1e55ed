"""engine.core.llm_critic

LLM critic layer for interpreter augmentation.

The critic is NOT the interpreter. It refines the rule-engine's candidate.
It never replaces deterministic guardrails.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

from engine.core.events import ForecastPayload
from engine.core.utils import _clamp

_SYSTEM_PROMPT = (
    "You are a critic reviewing a trading forecast produced by a rule-based system.\n"
    "Your job: identify if the confidence is mis-calibrated or if the signal should be suppressed.\n"
    "Be brief. Respond ONLY in JSON."
)


def _as_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_float(raw: str | None, default: float) -> float:
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True, slots=True)
class LLMCriticConfig:
    enabled: bool = False
    url: str = "https://api.openai.com/v1"
    key: str | None = None
    model: str = "gpt-4o-mini"
    timeout_s: float = 8.0
    shadow: bool = True

    @classmethod
    def from_env(cls) -> LLMCriticConfig:
        return cls(
            enabled=_as_bool(os.getenv("B1E55ED_LLM_CRITIC_ENABLED"), False),
            url=os.getenv("B1E55ED_LLM_CRITIC_URL", "https://api.openai.com/v1"),
            key=os.getenv("B1E55ED_LLM_CRITIC_KEY") or os.getenv("OPENAI_API_KEY"),
            model=os.getenv("B1E55ED_LLM_CRITIC_MODEL", "gpt-4o-mini"),
            timeout_s=_as_float(os.getenv("B1E55ED_LLM_CRITIC_TIMEOUT_S"), 8.0),
            shadow=_as_bool(os.getenv("B1E55ED_LLM_CRITIC_SHADOW"), True),
        )


@dataclass(frozen=True, slots=True)
class CritiqueResult:
    confidence_delta: float
    suppress: bool
    rationale: str
    raw_response: str
    error: str | None = None


class LLMCritic:
    def __init__(self, config: LLMCriticConfig) -> None:
        self.config = config

    @staticmethod
    def _summarize_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        top = signals[:5]
        out: list[dict[str, Any]] = []

        for sig in top:
            name = sig.get("name") or sig.get("signal_name") or sig.get("metric") or sig.get("event_type") or sig.get("symbol") or "signal"
            value = sig.get("value")
            if value is None:
                for key in (
                    "confidence",
                    "score",
                    "direction",
                    "signal_reason",
                    "basis_annualized",
                    "funding_annualized",
                    "meltup_score",
                ):
                    if key in sig and sig[key] is not None:
                        value = sig[key]
                        break
            if isinstance(value, (dict, list)):
                value = json.dumps(value, sort_keys=True)
            out.append({"name": str(name), "value": value})

        return out

    @staticmethod
    def _extract_content(response_json: dict[str, Any]) -> str:
        choices = response_json.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("missing choices in LLM response")

        first = choices[0]
        if not isinstance(first, dict):
            raise ValueError("invalid first choice in LLM response")

        message = first.get("message")
        if not isinstance(message, dict):
            raise ValueError("missing message in LLM response")

        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for chunk in content:
                if isinstance(chunk, str):
                    parts.append(chunk)
                    continue
                if isinstance(chunk, dict) and isinstance(chunk.get("text"), str):
                    parts.append(str(chunk["text"]))
            return "".join(parts)

        raise ValueError("unsupported message content shape")

    @staticmethod
    def _parse_json(raw_text: str) -> dict[str, Any]:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?", "", cleaned, count=1).strip()
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start < 0 or end <= start:
                raise
            parsed = json.loads(cleaned[start : end + 1])

        if not isinstance(parsed, dict):
            raise ValueError("critic response JSON must be an object")
        return parsed

    def critique(
        self,
        *,
        candidate: ForecastPayload,
        signals: list[dict],
        regime_tag: str,
        trailing_brier: float | None,
        aggregate_conviction: float | None,
    ) -> CritiqueResult:
        if not self.config.enabled:
            return CritiqueResult(confidence_delta=0.0, suppress=False, rationale="", raw_response="")

        try:
            if not self.config.key:
                raise ValueError("LLM critic API key missing")

            prompt_payload = {
                "candidate": {
                    "action": candidate.action,
                    "confidence": float(candidate.confidence),
                    "asset": candidate.asset,
                    "horizon": candidate.horizon,
                    "regime": regime_tag,
                },
                "trailing_brier_30d": trailing_brier,
                "aggregate_conviction": aggregate_conviction,
                "signals": self._summarize_signals(signals),
                "expected_response": {
                    "confidence_delta": -0.1,
                    "suppress": False,
                    "rationale": "one sentence",
                },
            }

            payload = {
                "model": self.config.model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(prompt_payload, sort_keys=True)},
                ],
            }
            headers = {
                "Authorization": f"Bearer {self.config.key}",
                "Content-Type": "application/json",
            }

            with httpx.Client(base_url=self.config.url.rstrip("/"), timeout=self.config.timeout_s) as client:
                response = client.post("/chat/completions", json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()

            raw_response = self._extract_content(data)
            parsed = self._parse_json(raw_response)

            delta = _clamp(float(parsed.get("confidence_delta", 0.0)), -0.3, 0.3)
            suppress = bool(parsed.get("suppress", False))
            rationale = str(parsed.get("rationale", "")).strip()

            return CritiqueResult(
                confidence_delta=delta,
                suppress=suppress,
                rationale=rationale,
                raw_response=raw_response,
            )

        except Exception as e:  # noqa: BLE001
            return CritiqueResult(
                confidence_delta=0.0,
                suppress=False,
                rationale="",
                raw_response="",
                error=str(e),
            )
