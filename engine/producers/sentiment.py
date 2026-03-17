"""engine.producers.sentiment

Market Sentiment Producer.

Fetches market sentiment metrics (fear/greed style indices, 7d change, and
optionally coarse CT sentiment) from a configured HTTP endpoint and emits
:class:`~engine.core.events.EventType.SIGNAL_SENTIMENT_V1`.

Data sources (tried in order):
1. Custom endpoint (B1E55ED_SENTIMENT_URL) — any URL that returns sentiment data
2. Alternative.me Fear & Greed Index (free, no auth) — directional signal only

The endpoint is configured via env and unit tests mock the injected
``context.client``.

Easter egg:
- Sentiment is the shadow of positioning.
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

import logging
from typing import Any

import httpx

from engine.core.events import EventType, SentimentSignalPayload
from engine.core.horizons import SENTIMENT_HORIZONS
from engine.core.models import Event
from engine.core.types import ProducerHealth, ProducerResult
from engine.producers.base import BaseProducer
from engine.producers.registry import register


def _dedupe_key(*, producer: str, symbol: str, ts: datetime) -> str:
    """Symbol + timestamp (+ producer) dedupe key."""

    return f"{EventType.SIGNAL_SENTIMENT_V1}:{producer}:{symbol}:{int(ts.timestamp())}"


# Gamelan logic: each section holds a fragment, and synthesis is the full melody.
@register("market-sentiment", domain="social")
class MarketSentimentProducer(BaseProducer):
    """Produce market sentiment signals for the configured universe."""

    schedule = "0 */1 * * *"  # hourly
    mcp_source_url: str | None = None  # override with MCP server URL when available

    def _endpoint(self) -> str | None:
        return os.getenv("B1E55ED_SENTIMENT_URL") or os.getenv("SENTIMENT_URL")

    def _collect_free(self) -> list[dict[str, Any]]:
        """Free fallback: Alternative.me Fear & Greed Index (current + 7d trend).

        Fetches the last 7 days of F&G values and returns one row per symbol
        in the configured universe, all sharing the same score. Reddit is
        intentionally excluded — it is already covered by social-intel producers
        and including it here would double-count that signal.
        """
        _log = logging.getLogger(__name__)
        try:
            resp = httpx.get(
                "https://api.alternative.me/fng/?limit=7",
                headers={"User-Agent": "b1e55ed/1.0"},
                timeout=10.0,
            )
            resp.raise_for_status()
            payload = resp.json()

            data = payload.get("data", [])
            if not data:
                return []

            # data[0] is the most recent entry
            current_value = float(data[0].get("value", 50))
            current_label: str = data[0].get("value_classification", "Neutral")

            # 7d change: most recent vs oldest in the window
            if len(data) >= 2:
                oldest_value = float(data[-1].get("value", current_value))
                change_7d = current_value - oldest_value
            else:
                change_7d = 0.0

            symbols = [s.upper().strip() for s in self.ctx.config.universe.symbols]
            results: list[dict[str, Any]] = []
            for sym in symbols:
                results.append(
                    {
                        "symbol": sym,
                        "fear_greed": current_value,
                        "fear_greed_change_7d": change_7d,
                        "ct_sentiment": current_label.lower(),
                        "data_source": "alternative_me_free",
                    }
                )
            return results

        except Exception as e:  # noqa: BLE001
            _log.warning("alternative_me_fng_failed: %s", e)
            return []

    def collect(self) -> list[dict[str, Any]]:
        url = self._endpoint()
        if not url:
            return self._collect_free()

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

            fear_greed = row.get("fear_greed")
            long_short_ratio = row.get("long_short_ratio")
            funding_annualized = row.get("funding_annualized")

            funding_extreme = False
            positioning_signal: str | None = None

            if funding_annualized is not None:
                try:
                    fa = float(funding_annualized)
                    funding_extreme = fa > 30.0 or fa < -10.0
                except (TypeError, ValueError):
                    funding_extreme = False

            if long_short_ratio is not None:
                try:
                    lsr = float(long_short_ratio)
                except (TypeError, ValueError):
                    lsr = 1.0
                if lsr > 2.0:
                    positioning_signal = "extreme_long"
                elif lsr < 0.5:
                    positioning_signal = "extreme_short"
                else:
                    positioning_signal = "neutral"
            elif fear_greed is not None:
                try:
                    fg = float(fear_greed)
                except (TypeError, ValueError):
                    fg = 50.0
                if fg >= 80:
                    positioning_signal = "extreme_long"
                elif fg <= 20:
                    positioning_signal = "extreme_short"
                else:
                    positioning_signal = "neutral"

            payload_obj = SentimentSignalPayload(
                symbol=sym,
                fear_greed=fear_greed,
                fear_greed_change_7d=row.get("fear_greed_change_7d"),
                ct_sentiment=row.get("ct_sentiment"),
                long_short_ratio=long_short_ratio,
                funding_extreme=funding_extreme,
                positioning_signal=positioning_signal,
            )
            payload = payload_obj.model_dump(mode="json")
            out.append(
                self.draft_event(
                    event_type=EventType.SIGNAL_SENTIMENT_V1,
                    payload=payload,
                    ts=ts,
                    observed_at=ts,
                    source=self.name,
                    dedupe_key=_dedupe_key(producer=self.name, symbol=sym, ts=ts),
                )
            )

        return out

    def run(self) -> ProducerResult:
        """Run with producer isolation: never raise.

        When no custom endpoint is configured, falls back to the free
        Alternative.me Fear & Greed Index. Only returns DEGRADED if that
        free source also fails (e.g. network outage).
        """

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
                    horizon_configs=SENTIMENT_HORIZONS,
                )
        except httpx.HTTPStatusError as e:
            code = getattr(e.response, "status_code", None)
            health = ProducerHealth.DEGRADED if code in (401, 403) else ProducerHealth.ERROR
            errors.append(f"HTTPStatusError: {code}")
        except Exception as e:  # noqa: BLE001
            health = ProducerHealth.ERROR
            errors.append(f"{type(e).__name__}: {e}")
            self.ctx.logger.exception("market_sentiment_run_failed")

        duration_ms = int((time.perf_counter() - start) * 1000)
        return ProducerResult(
            events_published=published,
            errors=errors,
            duration_ms=duration_ms,
            timestamp=datetime.now(tz=UTC),
            staleness_ms=None,
            health=health,
        )
