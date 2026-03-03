"""engine.core.prosecutor

Adversarial LLM pass — prosecutor, not curator.

The prosecutor's job: find the strongest bear case against the current
forecast. If the bear case is stronger than the bull case, suppress.
If the bear case is weak, the conviction increases.

Catches correlated inputs: when all signals agree because they're
measuring the same thing from different angles.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

from engine.core.events import ForecastPayload
from engine.core.utils import clamp

_PROSECUTOR_SYSTEM_PROMPT = (
    "You are a skeptical prosecutor reviewing a trading forecast.\n"
    "Your job: construct the STRONGEST possible case AGAINST this forecast.\n"
    "Find correlated inputs, missing risks, or reasons the thesis fails.\n"
    "Be concise. Respond ONLY in JSON with keys:\n"
    "  bear_strength (0.0-1.0): strength of the bear/counter case\n"
    "  bull_strength (0.0-1.0): strength of the bull/thesis case from the data\n"
    "  suppress (bool): true if bear_strength > bull_strength by more than 0.15\n"
    "  confidence_boost (float, 0.0-0.15): bonus if bear case is weak (bear_strength < 0.25)\n"
    "  rationale (str): one-sentence reason\n"
    "If uncertain, set suppress=false and confidence_boost=0."
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
class ProsecutorConfig:
    enabled: bool = False
    url: str = "https://api.openai.com/v1"
    key: str | None = None
    model: str = "gpt-4o-mini"
    timeout_s: float = 8.0
    # shadow=True: log result but never suppress/boost.
    shadow: bool = True

    @classmethod
    def from_env(cls) -> ProsecutorConfig:
        return cls(
            enabled=_as_bool(os.getenv("B1E55ED_PROSECUTOR_ENABLED"), False),
            url=os.getenv("B1E55ED_PROSECUTOR_URL", "https://api.openai.com/v1"),
            key=os.getenv("B1E55ED_PROSECUTOR_KEY") or os.getenv("OPENAI_API_KEY"),
            model=os.getenv("B1E55ED_PROSECUTOR_MODEL", "gpt-4o-mini"),
            timeout_s=_as_float(os.getenv("B1E55ED_PROSECUTOR_TIMEOUT_S"), 8.0),
            shadow=_as_bool(os.getenv("B1E55ED_PROSECUTOR_SHADOW"), True),
        )


@dataclass(frozen=True, slots=True)
class ProsecutionResult:
    bear_strength: float
    bull_strength: float
    suppress: bool
    confidence_boost: float
    rationale: str
    raw_response: str
    error: str | None = None


class Prosecutor:
    """Adversarial LLM pass — finds the strongest counter-case against a forecast."""

    def __init__(self, config: ProsecutorConfig) -> None:
        self.config = config

    @staticmethod
    def _summarize_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep only the most relevant fields for LLM context."""
        top = signals[:5]
        summarized: list[dict[str, Any]] = []
        for signal in top:
            keep = {k: v for k, v in signal.items() if v is not None and k not in ("reasoning_hash", "forecast_id")}
            summarized.append(keep)
        return summarized

    @staticmethod
    def _extract_content(response_json: dict[str, Any]) -> str:
        choices = response_json.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("missing choices in prosecutor LLM response")

        first = choices[0]
        if not isinstance(first, dict):
            raise ValueError("invalid first choice in prosecutor LLM response")

        message = first.get("message")
        if not isinstance(message, dict):
            raise ValueError("missing message in prosecutor LLM response")

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

        raise ValueError("unsupported prosecutor message content shape")

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
            raise ValueError("prosecutor response JSON must be an object")
        return parsed

    def prosecute(
        self,
        *,
        candidate: ForecastPayload,
        signals: list[dict[str, Any]],
        regime_tag: str = "unknown",
    ) -> ProsecutionResult:
        """Run the adversarial pass. Never raises; returns an error result on failure."""
        cfg = self.config
        if not cfg.enabled:
            return ProsecutionResult(
                bear_strength=0.0,
                bull_strength=1.0,
                suppress=False,
                confidence_boost=0.0,
                rationale="prosecutor_disabled",
                raw_response="",
            )

        prompt = (
            f"Forecast: action={candidate.action}, confidence={candidate.confidence:.2f}, "
            f"asset={candidate.asset}, horizon={candidate.horizon}, regime={regime_tag}\n"
            f"Signals: {json.dumps(self._summarize_signals(signals), separators=(',', ':'))}\n"
            "What is the strongest case AGAINST this forecast?"
        )

        try:
            if not cfg.key:
                raise ValueError("prosecutor API key missing")

            payload = {
                "model": cfg.model,
                "messages": [
                    {"role": "system", "content": _PROSECUTOR_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 200,
                "temperature": 0.1,
            }
            headers = {
                "Authorization": f"Bearer {cfg.key}",
                "Content-Type": "application/json",
            }

            with httpx.Client(base_url=cfg.url.rstrip("/"), timeout=cfg.timeout_s) as client:
                response = client.post("/chat/completions", json=payload, headers=headers)
                response.raise_for_status()
                response_json = response.json()

            raw_response = self._extract_content(response_json)
        except Exception as exc:  # noqa: BLE001
            return ProsecutionResult(
                bear_strength=0.0,
                bull_strength=1.0,
                suppress=False,
                confidence_boost=0.0,
                rationale="prosecutor_error",
                raw_response="",
                error=str(exc),
            )

        return self._parse(raw_response)

    @staticmethod
    def _parse(raw: str) -> ProsecutionResult:
        """Parse JSON from LLM response. Fails gracefully."""
        try:
            data = Prosecutor._parse_json(raw)
            bear = clamp(float(data.get("bear_strength", 0.0)), 0.0, 1.0)
            bull = clamp(float(data.get("bull_strength", 1.0)), 0.0, 1.0)

            suppress_raw = data.get("suppress", False)
            if isinstance(suppress_raw, bool):
                suppress = suppress_raw
            elif isinstance(suppress_raw, (int, float)):
                suppress = bool(suppress_raw)
            else:
                suppress = _as_bool(str(suppress_raw) if suppress_raw is not None else None, False)

            confidence_boost = clamp(float(data.get("confidence_boost", 0.0)), 0.0, 0.15)
            rationale = str(data.get("rationale", "")).strip()

            return ProsecutionResult(
                bear_strength=bear,
                bull_strength=bull,
                suppress=suppress,
                confidence_boost=confidence_boost,
                rationale=rationale,
                raw_response=raw,
            )
        except Exception as exc:  # noqa: BLE001
            return ProsecutionResult(
                bear_strength=0.0,
                bull_strength=1.0,
                suppress=False,
                confidence_boost=0.0,
                rationale="parse_error",
                raw_response=raw,
                error=str(exc),
            )
