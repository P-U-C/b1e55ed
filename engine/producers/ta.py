"""engine.producers.ta

Technical Analysis (TA) Producer.

Fetches pre-computed TA indicators from a configured HTTP endpoint and emits
:class:`~engine.core.events.EventType.SIGNAL_TA_V1`.

Free fallback uses the Binance Klines public API (no auth required) to compute
indicators locally when no custom endpoint is configured.

Easter egg:
- Charts change; patience doesn't.
"""

from __future__ import annotations

import asyncio
import os
import statistics
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
from engine.core.horizons import TECHNICAL_HORIZONS
from engine.core.interpreter import Interpreter, NullInterpreter
from engine.core.models import Event
from engine.core.regime import RegimeConfig, RegimeMatrix
from engine.core.types import ProducerHealth, ProducerResult
from engine.producers.base import BaseProducer
from engine.producers.registry import register

# ---------------------------------------------------------------------------
# TA helper functions (used by _collect_free)
# ---------------------------------------------------------------------------


def _ema(data: list[float], period: int) -> float | None:
    """Compute Exponential Moving Average."""
    if len(data) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = statistics.mean(data[:period])
    for val in data[period:]:
        ema = (val - ema) * multiplier + ema
    return ema


def _compute_rsi(closes: list[float], period: int = 14) -> float | None:
    """Compute Relative Strength Index."""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = statistics.mean(gains[:period])
    avg_loss = statistics.mean(losses[:period])
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _compute_atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float | None:
    """Compute Average True Range."""
    if len(closes) < period + 1:
        return None
    trs: list[float] = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    if len(trs) < period:
        return None
    atr = statistics.mean(trs[:period])
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


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

    # Settings discovery — the settings page reads these
    configurable_fields = [
        {
            "key": "B1E55ED_TA_URL",
            "label": "Custom TA endpoint",
            "type": "url",
            "required": False,
            "description": "Override the free Binance fallback with a custom TA data service",
        },
    ]

    def _custom_endpoint(self) -> str | None:
        """Optional custom/paid data endpoint override."""
        return os.getenv("B1E55ED_TA_URL") or os.getenv("TA_URL")

    def _collect_from_custom(self, url: str) -> list[dict[str, Any]]:
        """Fetch from a custom POST endpoint (original behaviour)."""
        symbols = [s.upper().strip() for s in self.ctx.config.universe.symbols]
        data: Any = asyncio.run(self.ctx.client.request_json("POST", url, expected=(list, dict), json={"symbols": symbols}))
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        if not isinstance(data, list):
            return []
        return [row for row in data if isinstance(row, dict)]

    _BINANCE_MISSING: set[str] = {"HYPE"}

    def _collect_free(self) -> list[dict[str, Any]]:
        """Free public API fallback (Binance Klines). Always available."""
        symbols = [s.upper().strip() for s in self.ctx.config.universe.symbols]
        results: list[dict[str, Any]] = []

        for sym in symbols[:10]:
            if sym in self._BINANCE_MISSING:
                continue
            try:
                resp = httpx.get(
                    "https://api.binance.com/api/v3/klines",
                    params={"symbol": f"{sym}USDT", "interval": "1h", "limit": 200},
                    timeout=10.0,
                )
                resp.raise_for_status()
                candles = resp.json()
                if len(candles) < 50:
                    continue

                closes = [float(c[4]) for c in candles]
                highs = [float(c[2]) for c in candles]
                lows = [float(c[3]) for c in candles]
                volumes = [float(c[5]) for c in candles]

                # RSI-14
                rsi = _compute_rsi(closes, 14)

                # EMAs
                ema_20 = _ema(closes, 20)
                ema_50 = _ema(closes, 50)
                ema_200 = _ema(closes, 200) if len(closes) >= 200 else None

                # Bollinger Bands (20-period, 2 std)
                bb_window = closes[-20:]
                bb_mid = statistics.mean(bb_window)
                bb_std = statistics.stdev(bb_window)
                bb_upper = bb_mid + 2 * bb_std
                bb_lower = bb_mid - 2 * bb_std
                current = closes[-1]
                bb_range = bb_upper - bb_lower
                bb_position = (current - bb_lower) / bb_range if bb_range > 0 else 0.5

                # ATR-14
                atr = _compute_atr(highs, lows, closes, 14)

                # Volume ratio (current vs 20-period avg)
                vol_avg = statistics.mean(volumes[-20:]) if len(volumes) >= 20 else volumes[-1]
                volume_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1.0

                # Trend detection
                trend = "bullish" if ema_20 and ema_50 and ema_20 > ema_50 else "bearish"
                trend_strength = abs(ema_20 - ema_50) / current if ema_20 and ema_50 and current > 0 else 0.0
                trend_strength = min(trend_strength * 10, 1.0)  # normalize to 0-1

                # Volatility compression
                bb_width = (bb_upper - bb_lower) / bb_mid if bb_mid > 0 else 0
                volatility_compression = bb_width < 0.04

                # Support / resistance (simple: recent low/high)
                recent_low = min(lows[-20:])
                recent_high = max(highs[-20:])
                support_distance = (current - recent_low) / current if current > 0 else 0
                resistance_distance = (recent_high - current) / current if current > 0 else 0

                results.append(
                    {
                        "symbol": sym,
                        "rsi_14": round(rsi, 2) if rsi else None,
                        "ema_20": round(ema_20, 4) if ema_20 else None,
                        "ema_50": round(ema_50, 4) if ema_50 else None,
                        "ema_200": round(ema_200, 4) if ema_200 else None,
                        "bb_upper": round(bb_upper, 4),
                        "bb_lower": round(bb_lower, 4),
                        "bb_mid": round(bb_mid, 4),
                        "bb_position": round(bb_position, 4),
                        "bb_width": round(bb_width, 4),
                        "atr_14": round(atr, 4) if atr else None,
                        "volume_ratio": round(volume_ratio, 2),
                        "trend": trend,
                        "trend_strength": round(trend_strength, 3),
                        "support_distance": round(support_distance, 4),
                        "resistance_distance": round(resistance_distance, 4),
                        "volatility_compression": volatility_compression,
                        "breakout_failure": False,
                        "data_source": "binance_free",
                    }
                )
            except Exception as e:  # noqa: BLE001
                self.ctx.logger.warning("ta_free_symbol_failed symbol=%s error=%s", sym, e)
                continue

        return results

    def collect(self) -> list[dict[str, Any]]:
        url = self._custom_endpoint()
        if url:
            try:
                return self._collect_from_custom(url)
            except Exception:  # noqa: BLE001
                self.ctx.logger.warning("custom_endpoint_failed_falling_back url=%s", url)
        # Fall back to free API
        return self._collect_free()

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

            symbols = [s.upper().strip() for s in self.ctx.config.universe.symbols]
            signal_payloads = [e.payload for e in events]
            for symbol in symbols:
                self.emit_forecasts_multi_horizon(
                    asset=symbol,
                    signals=signal_payloads,
                    regime_tag="unknown",
                    visible_signal_refs=[],
                    horizon_configs=TECHNICAL_HORIZONS,
                )
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
