"""engine.producers.sentiment

Market Sentiment Producer.

Fetches market sentiment metrics (fear/greed style indices, 7d change, and
optionally coarse CT sentiment) from a configured HTTP endpoint and emits
:class:`~engine.core.events.EventType.SIGNAL_SENTIMENT_V1`.

The endpoint is configured via env and unit tests mock the injected
``context.client``.

Easter egg:
- Sentiment is the shadow of positioning.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from engine.core.events import EventType, SentimentSignalPayload
from engine.core.models import Event
from engine.core.types import ProducerHealth, ProducerResult
from engine.producers.base import BaseProducer
from engine.producers.registry import register


def _dedupe_key(*, producer: str, symbol: str, ts: datetime) -> str:
    """Symbol + timestamp (+ producer) dedupe key."""

    return f"{EventType.SIGNAL_SENTIMENT_V1}:{producer}:{symbol}:{int(ts.timestamp())}"


@register("market-sentiment", domain="social")
class MarketSentimentProducer(BaseProducer):
    """Produce market sentiment signals for the configured universe."""

    schedule = "0 */1 * * *"  # hourly

    def _endpoint(self) -> str | None:
        return os.getenv("B1E55ED_SENTIMENT_URL") or os.getenv("SENTIMENT_URL")

    def collect(self) -> list[dict[str, Any]]:
        url = self._endpoint()
        if not url:
            self.ctx.logger.warning("sentiment_endpoint_missing")
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

            payload_obj = SentimentSignalPayload(
                symbol=sym,
                fear_greed=row.get("fear_greed"),
                fear_greed_change_7d=row.get("fear_greed_change_7d"),
                ct_sentiment=row.get("ct_sentiment"),
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
