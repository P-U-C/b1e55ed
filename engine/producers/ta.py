"""engine.producers.ta

Technical Analysis (TA) Producer.

Fetches pre-computed TA indicators from a configured HTTP endpoint and emits
:class:`~engine.core.events.EventType.SIGNAL_TA_V1`.

The endpoint is configured via env and unit tests mock the injected
``context.client``.

Easter egg:
- Charts change; patience doesn't.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from typing import Any

import httpx

from engine.core.events import (
    AbstentionReason,
    EventType,
    ForecastLifecycleState,
    ForecastPayload,
    TASignalPayload,
)
from engine.core.forecast import abstain, compute_reasoning_hash, make_forecast_id
from engine.core.interpreter import Interpreter, NullInterpreter
from engine.core.models import Event
from engine.core.regime import RegimeConfig, RegimeMatrix
from engine.core.types import ProducerHealth, ProducerResult
from engine.producers.base import BaseProducer
from engine.producers.registry import register


def _dedupe_key(*, producer: str, symbol: str, ts: datetime) -> str:
    """Symbol + timestamp (+ producer) dedupe key."""

    return f"{EventType.SIGNAL_TA_V1}:{producer}:{symbol}:{int(ts.timestamp())}"


class TechnicalInterpreter(Interpreter):
    """Rule-based interpreter for TA signals → FORECAST_V1.

    P3.3: Uses volatility compression and breakout failure as key differentiators.
    """

    regime_matrix = RegimeMatrix(
        configs={
            "BULL": RegimeConfig(confidence_multiplier=1.1),
            "BEAR": RegimeConfig(confidence_multiplier=0.8, min_confidence=0.4),
            "CRISIS": RegimeConfig(abstain=True),
            "TRANSITION": RegimeConfig(confidence_multiplier=0.9),
        }
    )

    def interpret(
        self,
        *,
        asset: str,
        horizon: str,
        signals: list[dict[str, Any]],
        regime_tag: str = "unknown",
        visible_signal_refs: list[str] | None = None,
    ) -> ForecastPayload:
        refs = visible_signal_refs or []
        asset_sigs = [s for s in signals if str(s.get("symbol", "")).upper() == asset.upper()]
        if not asset_sigs:
            return abstain(
                source=self.source,
                asset=asset,
                horizon=horizon,
                reason=AbstentionReason.INSUFFICIENT_DATA,
                regime_tag=regime_tag,
                visible_signal_refs=refs,
            )

        sig = asset_sigs[0]
        trend = sig.get("trend")

        try:
            strength = float(sig.get("trend_strength") or 0.0)
        except (TypeError, ValueError):
            strength = 0.0

        rsi = sig.get("rsi_14")
        volatility_compression = bool(sig.get("volatility_compression", False))
        breakout_failure = bool(sig.get("breakout_failure", False))

        if trend not in ("bullish", "bearish") or strength < 0.3:
            return abstain(
                source=self.source,
                asset=asset,
                horizon=horizon,
                reason=AbstentionReason.INSUFFICIENT_DATA,
                regime_tag=regime_tag,
                visible_signal_refs=refs,
            )

        action = "long" if trend == "bullish" else "short"
        confidence = min(0.35 + strength * 0.5, 0.85)

        if rsi is not None:
            try:
                rsi_val = float(rsi)
            except (TypeError, ValueError):
                rsi_val = None
            if rsi_val is not None and ((action == "long" and rsi_val > 70) or (action == "short" and rsi_val < 30)):
                confidence *= 0.85

        if volatility_compression:
            confidence *= 1.15
        if breakout_failure:
            confidence *= 0.5

        confidence = min(confidence, 0.90)

        if confidence < 0.3:
            return abstain(
                source=self.source,
                asset=asset,
                horizon=horizon,
                reason=AbstentionReason.LOW_CONFIDENCE,
                regime_tag=regime_tag,
                visible_signal_refs=refs,
            )

        return ForecastPayload(
            forecast_id=make_forecast_id(),
            asset=asset,
            horizon=horizon,
            action=action,
            confidence=round(confidence, 3),
            source=self.source,
            regime_tag=regime_tag,
            lifecycle_state=ForecastLifecycleState.NEW,
            reasoning_hash=compute_reasoning_hash(
                {
                    "action": action,
                    "confidence": confidence,
                    "trend": trend,
                    "volatility_compression": volatility_compression,
                    "breakout_failure": breakout_failure,
                },
                "",
                str(sig.get("trend", "")),
            ),
            visible_signal_refs=refs,
            used_signal_refs=refs,
        )


@register("technical-analysis", domain="technical")
class TechnicalAnalysisProducer(BaseProducer):
    schedule = "*/15 * * * *"
    mcp_source_url: str | None = None  # override with MCP server URL when available
    interpreter: Interpreter | NullInterpreter | None = TechnicalInterpreter()

    def _endpoint(self) -> str | None:
        return os.getenv("B1E55ED_TA_URL") or os.getenv("TA_URL")

    def collect(self) -> list[dict[str, Any]]:
        url = self._endpoint()
        if not url:
            self.ctx.logger.warning("ta_endpoint_missing")
            return []

        symbols = [s.upper().strip() for s in self.ctx.config.universe.symbols]
        data: Any = asyncio.run(self.ctx.client.request_json("POST", url, expected=(list, dict), json={"symbols": symbols}))
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        if not isinstance(data, list):
            return []
        return [row for row in data if isinstance(row, dict)]

    def normalize(self, raw: list[dict[str, Any]]) -> list[Event]:
        ts = datetime.now(tz=UTC)
        out: list[Event] = []

        for row in raw:
            sym = str(row.get("symbol") or row.get("asset") or "").upper().strip()
            if not sym:
                continue

            bb_upper = row.get("bb_upper")
            bb_lower = row.get("bb_lower")
            bb_mid = row.get("bb_mid") or row.get("ema_20")

            bb_width: float | None = None
            volatility_compression = False
            if bb_upper is not None and bb_lower is not None and bb_mid is not None:
                try:
                    bb_mid_val = float(bb_mid)
                    if bb_mid_val > 0:
                        bb_width = round((float(bb_upper) - float(bb_lower)) / bb_mid_val, 4)
                        volatility_compression = bb_width < 0.04
                except (TypeError, ValueError):
                    bb_width = None

            payload_obj = TASignalPayload(
                symbol=sym,
                rsi_14=row.get("rsi_14"),
                ema_20=row.get("ema_20"),
                ema_50=row.get("ema_50"),
                ema_200=row.get("ema_200"),
                bb_position=row.get("bb_position"),
                volume_ratio=row.get("volume_ratio"),
                trend=row.get("trend"),
                trend_strength=row.get("trend_strength"),
                support_distance=row.get("support_distance"),
                resistance_distance=row.get("resistance_distance"),
                bb_width=bb_width,
                atr_14=row.get("atr_14"),
                volatility_compression=volatility_compression,
                breakout_failure=bool(row.get("breakout_failure", False)),
            )
            payload = payload_obj.model_dump(mode="json")
            out.append(
                self.draft_event(
                    event_type=EventType.SIGNAL_TA_V1,
                    payload=payload,
                    ts=ts,
                    observed_at=ts,
                    source=self.name,
                    dedupe_key=_dedupe_key(producer=self.name, symbol=sym, ts=ts),
                )
            )

        return out

    def run(self) -> ProducerResult:
        """Run with producer isolation: never raise."""

        start = time.perf_counter()
        errors: list[str] = []
        published = 0
        health: ProducerHealth = ProducerHealth.OK

        try:
            raw = self.collect()
            if not raw:
                health = ProducerHealth.DEGRADED
            events = self.normalize(raw)
            published = self.publish(events)
        except httpx.HTTPStatusError as e:
            code = getattr(e.response, "status_code", None)
            health = ProducerHealth.DEGRADED if code in (401, 403) else ProducerHealth.ERROR
            errors.append(f"HTTPStatusError: {code}")
        except Exception as e:  # noqa: BLE001
            health = ProducerHealth.ERROR
            errors.append(f"{type(e).__name__}: {e}")
            self.ctx.logger.exception("ta_run_failed")

        duration_ms = int((time.perf_counter() - start) * 1000)
        return ProducerResult(
            events_published=published,
            errors=errors,
            duration_ms=duration_ms,
            timestamp=datetime.now(tz=UTC),
            staleness_ms=None,
            health=health,
        )
