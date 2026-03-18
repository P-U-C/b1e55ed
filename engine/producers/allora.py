"""engine.producers.allora

Allora Network Inference Consumer Producer.

Consumes aggregated ML price predictions from the Allora Network as AI consensus
signals and emits :class:`~engine.core.events.EventType.SIGNAL_ACI_V1`.

The Allora Network is a decentralised ML inference marketplace where workers
submit price predictions on-chain and the network aggregates them into a consensus
inference. This producer converts those predictions into directional signals by
comparing them against the current Binance spot price.

Configuration (env):
- ``ALLORA_API_KEY`` — Required. Get a free key at developer.allora.network.
  If not set the producer registers fine and reports OK but emits nothing
  (no repeated warnings; one info log on first poll).

Topic mapping is extensible via the module-level ``ALLORA_TOPICS`` dict.
"""

from __future__ import annotations

import asyncio
import logging
import math
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

from engine.core.events import ACISignalPayload, EventType, payload_hash
from engine.core.models import Event
from engine.core.types import ProducerHealth, ProducerResult
from engine.producers.base import BaseProducer
from engine.producers.registry import register

_log = logging.getLogger(__name__)

# ── Topic registry ────────────────────────────────────────────────────────────
# Add new Allora topics here. Keys are Allora topic IDs.
ALLORA_TOPICS: dict[int, dict[str, str]] = {
    13: {"symbol": "ETH", "binance_symbol": "ETHUSDT", "description": "ETH 5-minute price"},
    14: {"symbol": "BTC", "binance_symbol": "BTCUSDT", "description": "BTC 5-minute price"},
    20: {"symbol": "ETH", "binance_symbol": "ETHUSDT", "description": "ETH 10-minute price"},
    69: {"symbol": "BTC", "binance_symbol": "BTCUSDT", "description": "BTC 24-hour price"},
}

_BINANCE_PRICE_URL = "https://api.binance.com/api/v3/ticker/price"

# Flag: log missing-key warning exactly once per process lifetime.
_warned_no_key: bool = False


# ── Helpers ───────────────────────────────────────────────────────────────────


def _fifteen_min_bucket(ts: datetime) -> int:
    """Snap *ts* to a 15-minute epoch bucket (seconds since epoch, rounded down)."""
    epoch = int(ts.timestamp())
    return (epoch // 900) * 900


def _compute_score(predicted: float, current: float) -> float:
    """Convert predicted / current prices to a consensus_score in [-10, 10].

    Algorithm:
    - raw_pct = log(predicted / current) * 100
    - Neutral band  ±0.5 %  → score 0
    - Outside band  → score = clamp(raw_pct, -8, 8)
    """
    if current <= 0 or predicted <= 0:
        return 0.0
    raw_pct = math.log(predicted / current) * 100.0
    if abs(raw_pct) <= 0.5:
        return 0.0
    return max(-8.0, min(8.0, raw_pct))


def _build_dedupe_key(*, symbol: str, topic_id: int, bucket: int) -> str:
    """Deterministic dedupe key: signal type + producer + symbol + topic + bucket."""
    raw = f"{symbol}:{topic_id}:{bucket}"
    return f"{EventType.SIGNAL_ACI_V1}:allora-inference:{payload_hash(raw)}"


# ── Async fetch helpers ───────────────────────────────────────────────────────


async def _fetch_binance_prices(binance_symbols: list[str]) -> dict[str, float]:
    """Fetch current spot prices from Binance for *binance_symbols* (e.g. BTCUSDT)."""
    prices: dict[str, float] = {}
    async with httpx.AsyncClient(timeout=10.0) as client:
        for sym in binance_symbols:
            try:
                resp = await client.get(_BINANCE_PRICE_URL, params={"symbol": sym})
                resp.raise_for_status()
                prices[sym] = float(resp.json()["price"])
            except Exception as exc:  # noqa: BLE001
                _log.warning("allora_binance_price_failed symbol=%s err=%s", sym, exc)
    return prices


async def _fetch_allora_inferences(api_key: str) -> list[dict[str, Any]]:
    """Fetch inferences from all configured Allora topics.

    Failures on individual topics are logged and skipped — the rest still run.
    Returns a list of dicts ready for AlloraInferenceProducer.normalize().
    """
    try:
        from allora_sdk.api_client import AlloraAPIClient  # noqa: PLC0415
    except ImportError:
        _log.error("allora_sdk not installed: pip install allora_sdk")
        return []

    client = AlloraAPIClient(api_key=api_key)

    # Batch current-price fetch (de-duplicated by Binance symbol).
    unique_binance = list({info["binance_symbol"] for info in ALLORA_TOPICS.values()})
    prices = await _fetch_binance_prices(unique_binance)

    results: list[dict[str, Any]] = []

    for topic_id, topic_info in ALLORA_TOPICS.items():
        try:
            inference = await client.get_inference_by_topic_id(topic_id)
            predicted = float(inference.inference_data.network_inference_normalized)

            # confidence_interval_values may not exist on all topics.
            ci_values: list[float] = []
            try:
                raw_ci = inference.inference_data.confidence_interval_values
                if raw_ci:
                    ci_values = [float(v) for v in raw_ci]
            except AttributeError:
                pass

            binance_sym = topic_info["binance_symbol"]
            current_price = prices.get(binance_sym)
            if current_price is None:
                _log.warning("allora_no_current_price topic=%d sym=%s", topic_id, binance_sym)
                continue

            results.append(
                {
                    "topic_id": topic_id,
                    "symbol": topic_info["symbol"],
                    "binance_symbol": binance_sym,
                    "predicted": predicted,
                    "current": current_price,
                    "ci_values": ci_values,
                }
            )

        except Exception as exc:  # noqa: BLE001
            _log.warning("allora_topic_fetch_failed topic=%d err=%s", topic_id, exc)
            continue  # Skip this topic; keep going.

    return results


# ── Producer ─────────────────────────────────────────────────────────────────


@register("allora-inference", domain="curator")
class AlloraInferenceProducer(BaseProducer):
    """Allora Network ML consensus price predictions → ACI signals.

    Emits one SIGNAL_ACI_V1 event per topic per 15-minute window.
    Each event carries a directional consensus_score derived from comparing
    Allora's aggregated inference to the live Binance spot price.
    """

    schedule = "*/15 * * * *"

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _api_key(self) -> str | None:
        return os.getenv("ALLORA_API_KEY")

    # ── BaseProducer interface ────────────────────────────────────────────────

    def collect(self) -> list[dict[str, Any]]:
        api_key = self._api_key()
        if not api_key:
            return []
        return asyncio.run(_fetch_allora_inferences(api_key))

    def normalize(self, raw: list[dict[str, Any]]) -> list[Event]:
        ts = datetime.now(tz=UTC)
        bucket = _fifteen_min_bucket(ts)
        events: list[Event] = []

        for row in raw:
            symbol: str = row["symbol"]
            topic_id: int = row["topic_id"]
            predicted: float = row["predicted"]
            current: float = row["current"]
            ci_values: list[float] = row.get("ci_values", [])

            score = _compute_score(predicted, current)

            # Allora aggregates many worker inferences; exact counts aren't in the API.
            # Use a reasonable proxy: 50 queried, responded = len(CI values) if known.
            models_queried = 50
            models_responded = len(ci_values) if ci_values else 20
            dispersion = statistics.stdev(ci_values) if len(ci_values) >= 2 else 0.0

            payload_obj = ACISignalPayload(
                symbol=symbol,
                consensus_score=score,
                models_queried=models_queried,
                models_responded=models_responded,
                dispersion=dispersion,
            )
            payload = payload_obj.model_dump(mode="json")
            dk = _build_dedupe_key(symbol=symbol, topic_id=topic_id, bucket=bucket)

            events.append(
                self.draft_event(
                    event_type=EventType.SIGNAL_ACI_V1,
                    payload=payload,
                    ts=ts,
                    observed_at=ts,
                    source=self.name,
                    dedupe_key=dk,
                )
            )

        return events

    def run(self) -> ProducerResult:
        """Run with producer isolation: never raise.

        When ALLORA_API_KEY is not configured, return OK with zero events.
        One info log on first missing-key poll; silent on subsequent polls.
        """
        global _warned_no_key  # noqa: PLW0603

        start = time.perf_counter()

        if not self._api_key():
            if not _warned_no_key:
                _log.info("allora_no_api_key: set ALLORA_API_KEY to enable Allora inference signals")
                _warned_no_key = True
            return ProducerResult(
                events_published=0,
                errors=[],
                duration_ms=int((time.perf_counter() - start) * 1000),
                timestamp=datetime.now(tz=UTC),
                staleness_ms=None,
                health=ProducerHealth.OK,
            )

        errors: list[str] = []
        published = 0
        health = ProducerHealth.OK

        try:
            raw = self.collect()
            events = self.normalize(raw)
            published = self.publish(events)
        except Exception as exc:  # noqa: BLE001
            health = ProducerHealth.ERROR
            errors.append(f"{type(exc).__name__}: {exc}")
            self.ctx.logger.exception("allora_run_failed")

        return ProducerResult(
            events_published=published,
            errors=errors,
            duration_ms=int((time.perf_counter() - start) * 1000),
            timestamp=datetime.now(tz=UTC),
            staleness_ms=None,
            health=health,
        )
