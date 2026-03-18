"""engine.producers.events

Market Events Producer.

Treats the configured endpoint as a simple HTTP poller that returns a list of
"events" / catalysts per symbol, then emits
:class:`~engine.core.events.EventType.SIGNAL_EVENTS_V1`.

Data sources (tried in order):
1. Custom endpoint (B1E55ED_EVENTS_URL) — any URL that returns event/catalyst data
2. CryptoPanic free API (no auth) — public news with vote-based sentiment scoring

Easter egg:
- News is noise; catalysts are structure.
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

from engine.core.events import EventsSignalPayload, EventType, payload_hash
from engine.core.models import Event
from engine.core.types import ProducerHealth, ProducerResult
from engine.producers.base import BaseProducer
from engine.producers.registry import register


def _dedupe_key(*, producer: str, payload: dict[str, Any]) -> str:
    """Deterministic dedupe key based on canonicalized payload."""

    return f"{EventType.SIGNAL_EVENTS_V1}:{producer}:{payload_hash(payload)}"


@register("market-events", domain="events")
class MarketEventsProducer(BaseProducer):
    schedule = "*/30 * * * *"
    mcp_source_url: str | None = None  # override with MCP server URL when available

    # Settings discovery — the settings page reads these
    configurable_fields = [
        {
            "key": "B1E55ED_EVENTS_URL",
            "label": "Market events data endpoint",
            "type": "url",
            "required": False,
            "description": (
                "Custom HTTP endpoint for market event/catalyst data. "
                "Without this, CryptoPanic free API is used for directional news sentiment. "
                "Expected response: [{symbol, catalysts, headline_sentiment, impact_score}]"
            ),
        },
    ]

    def _custom_endpoint(self) -> str | None:
        """Optional custom/paid data endpoint override."""
        return os.getenv("B1E55ED_EVENTS_URL") or os.getenv("EVENTS_URL")

    def _collect_cryptopanic(self) -> list[dict[str, Any]]:
        """Free fallback: CryptoPanic public news API (no auth required).

        Fetches recent news per symbol, computes a sentiment score from
        bullish/bearish vote counts, and returns one row per symbol.
        Rate-limit friendly: one request per symbol, results deduplicated
        by payload hash (30-min window via producer schedule).
        """
        _log = logging.getLogger(__name__)
        symbols = [s.upper().strip() for s in self.ctx.config.universe.symbols]
        results: list[dict[str, Any]] = []

        for sym in symbols:
            try:
                resp = httpx.get(
                    "https://cryptopanic.com/api/free/v1/posts/",
                    params={"currencies": sym, "kind": "news", "public": "true"},
                    headers={"User-Agent": "b1e55ed/1.0"},
                    timeout=10.0,
                )
                resp.raise_for_status()
                data = resp.json()

                posts = data.get("results", [])
                if not posts:
                    continue

                catalysts: list[str] = []
                sentiment_scores: list[float] = []

                for post in posts[:10]:  # cap at 10 posts per symbol
                    title = post.get("title", "").strip()
                    if title:
                        catalysts.append(title)

                    votes = post.get("votes", {})
                    bullish = int(votes.get("positive", 0) or 0)
                    bearish = int(votes.get("negative", 0) or 0)
                    total = bullish + bearish
                    score = (bullish - bearish) / max(total, 1)
                    sentiment_scores.append(score)

                if not sentiment_scores:
                    continue

                avg_sentiment = sum(sentiment_scores) / len(sentiment_scores)
                impact = min(abs(avg_sentiment), 1.0)

                results.append(
                    {
                        "symbol": sym,
                        "headline_sentiment": avg_sentiment,
                        "impact_score": impact,
                        "event_count": len(catalysts),
                        "catalysts": catalysts[:5],  # top 5 headlines
                        "data_source": "cryptopanic_free",
                    }
                )

            except Exception as e:  # noqa: BLE001
                _log.warning("cryptopanic_failed: %s %s", sym, e)

        return results

    def collect(self) -> list[dict[str, Any]]:
        url = self._custom_endpoint()
        if not url:
            return self._collect_cryptopanic()

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

            catalysts_raw = row.get("catalysts") or row.get("events") or []
            catalysts: list[str] = []
            if isinstance(catalysts_raw, list):
                catalysts = [str(x) for x in catalysts_raw if x is not None and str(x).strip()]
            elif isinstance(catalysts_raw, str) and catalysts_raw.strip():
                catalysts = [catalysts_raw.strip()]

            event_count = row.get("event_count")
            if not isinstance(event_count, int):
                event_count = len(catalysts)

            payload_obj = EventsSignalPayload(
                symbol=sym,
                headline_sentiment=row.get("headline_sentiment"),
                impact_score=row.get("impact_score"),
                event_count=event_count,
                catalysts=catalysts,
            )
            payload = payload_obj.model_dump(mode="json")

            out.append(
                self.draft_event(
                    event_type=EventType.SIGNAL_EVENTS_V1,
                    payload=payload,
                    ts=ts,
                    observed_at=ts,
                    source=self.name,
                    dedupe_key=_dedupe_key(producer=self.name, payload=payload),
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
            self.ctx.logger.exception("events_run_failed")

        duration_ms = int((time.perf_counter() - start) * 1000)
        return ProducerResult(
            events_published=published,
            errors=errors,
            duration_ms=duration_ms,
            timestamp=datetime.now(tz=UTC),
            staleness_ms=None,
            health=health,
        )
