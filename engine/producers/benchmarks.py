"""engine.producers.benchmarks

Baseline signal producers for attribution benchmarking.

Four naive strategies running through the same attribution/karma pipeline as real
producers. Their karma scores answer: "how much better is the brain than naive?"
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017
from typing import Any

from engine.core.events import EventType
from engine.core.models import Event
from engine.producers.base import BaseProducer
from engine.producers.registry import register

BENCHMARK_SYMBOLS = ["BTC", "ETH", "SOL"]


def _dedupe_key(producer: str, symbol: str, ts: datetime) -> str:
    return f"{EventType.SIGNAL_BENCHMARK_V1}:{producer}:{symbol}:{int(ts.timestamp())}"


def _ema(prices: list[float], period: int) -> float:
    """Exponential moving average."""
    if not prices:
        return 0.0
    k = 2 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = p * k + ema * (1 - k)
    return ema


@register("benchmark.momentum", domain="events")
class BenchmarkMomentumProducer(BaseProducer):
    """Naive EMA-20 crossover. Fixed confidence 0.50."""

    schedule = "*/30 * * * *"

    def collect(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for symbol in BENCHMARK_SYMBOLS:
            prices = self._get_prices_from_db(symbol)
            if len(prices) < 2:
                continue
            current = prices[-1]
            ema_20 = _ema(prices, 20)
            direction = "long" if current > ema_20 else "short"
            results.append(
                {
                    "symbol": symbol,
                    "direction": direction,
                    "confidence": 0.50,
                    "reasoning": f"price={current:.2f} vs ema20={ema_20:.2f}",
                }
            )
        return results

    def _get_prices_from_db(self, symbol: str) -> list[float]:
        try:
            rows = self.ctx.db.conn.execute(
                "SELECT payload FROM events WHERE type = ? AND json_extract(payload, '$.symbol') = ? ORDER BY ts DESC LIMIT 20",
                (str(EventType.SIGNAL_PRICE_WS_V1), symbol),
            ).fetchall()
            prices: list[float] = []
            for r in rows:
                p = json.loads(r[0]) if isinstance(r[0], str) else r[0]
                if p.get("price") is not None:
                    prices.append(float(p["price"]))
            return list(reversed(prices))
        except Exception:
            return []

    def normalize(self, raw: list[dict[str, Any]]) -> list[Event]:
        ts = datetime.now(tz=UTC)
        out: list[Event] = []
        for row in raw:
            payload = {
                "symbol": row["symbol"],
                "direction": row["direction"],
                "confidence": row["confidence"],
                "source": self.name,
                "reasoning": row.get("reasoning"),
            }
            out.append(
                self.draft_event(
                    event_type=EventType.SIGNAL_BENCHMARK_V1,
                    payload=payload,
                    ts=ts,
                    observed_at=ts,
                    source=self.name,
                    dedupe_key=_dedupe_key(self.name, row["symbol"], ts),
                )
            )
        return out


@register("benchmark.flat", domain="events")
class BenchmarkFlatProducer(BaseProducer):
    """Always-flat baseline. Catches overtrading."""

    schedule = "*/30 * * * *"

    def collect(self) -> list[dict[str, Any]]:
        return [{"symbol": s, "direction": "flat", "confidence": 0.0} for s in BENCHMARK_SYMBOLS]

    def normalize(self, raw: list[dict[str, Any]]) -> list[Event]:
        ts = datetime.now(tz=UTC)
        out: list[Event] = []
        for row in raw:
            payload = {
                "symbol": row["symbol"],
                "direction": "flat",
                "confidence": 0.0,
                "source": self.name,
            }
            out.append(
                self.draft_event(
                    event_type=EventType.SIGNAL_BENCHMARK_V1,
                    payload=payload,
                    ts=ts,
                    observed_at=ts,
                    source=self.name,
                    dedupe_key=_dedupe_key(self.name, row["symbol"], ts),
                )
            )
        return out


@register("benchmark.equal_weight", domain="events")
class BenchmarkEqualWeightProducer(BaseProducer):
    """Equal-weight vote across all recent signals from real producers."""

    schedule = "*/30 * * * *"

    def collect(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        cutoff = (datetime.now(tz=UTC) - timedelta(minutes=30)).isoformat()
        signal_types = (
            str(EventType.SIGNAL_TA_V1),
            str(EventType.SIGNAL_TRADFI_V1),
            str(EventType.SIGNAL_ONCHAIN_V1),
            str(EventType.SIGNAL_SOCIAL_V1),
            str(EventType.SIGNAL_SENTIMENT_V1),
        )
        for symbol in BENCHMARK_SYMBOLS:
            try:
                rows = self.ctx.db.conn.execute(
                    "SELECT payload FROM events WHERE ts >= ? AND type IN (?, ?, ?, ?, ?) AND json_extract(payload, '$.symbol') = ?",
                    (cutoff, *signal_types, symbol),
                ).fetchall()
            except Exception:
                continue

            if not rows:
                continue

            long_count = 0
            short_count = 0
            for r in rows:
                p = json.loads(r[0]) if isinstance(r[0], str) else r[0]
                d = p.get("direction") or p.get("trend")
                if d in ("long", "bullish"):
                    long_count += 1
                elif d in ("short", "bearish"):
                    short_count += 1

            total = long_count + short_count
            if total == 0:
                continue

            direction = "long" if long_count >= short_count else "short"
            confidence = abs(long_count - short_count) / total
            results.append(
                {
                    "symbol": symbol,
                    "direction": direction,
                    "confidence": round(confidence, 4),
                    "reasoning": f"votes: {long_count} long, {short_count} short",
                }
            )
        return results

    def normalize(self, raw: list[dict[str, Any]]) -> list[Event]:
        ts = datetime.now(tz=UTC)
        out: list[Event] = []
        for row in raw:
            payload = {
                "symbol": row["symbol"],
                "direction": row["direction"],
                "confidence": row["confidence"],
                "source": self.name,
                "reasoning": row.get("reasoning"),
            }
            out.append(
                self.draft_event(
                    event_type=EventType.SIGNAL_BENCHMARK_V1,
                    payload=payload,
                    ts=ts,
                    observed_at=ts,
                    source=self.name,
                    dedupe_key=_dedupe_key(self.name, row["symbol"], ts),
                )
            )
        return out


@register("benchmark.discretionary", domain="events")
class BenchmarkDiscretionaryProducer(BaseProducer):
    """Reads operator-injected signals from the discretionary_signals table."""

    schedule = "*/30 * * * *"

    def collect(self) -> list[dict[str, Any]]:
        now = datetime.now(tz=UTC).isoformat()
        try:
            rows = self.ctx.db.conn.execute(
                "SELECT symbol, direction, confidence, reasoning FROM discretionary_signals WHERE expires_at IS NULL OR expires_at > ?",
                (now,),
            ).fetchall()
        except Exception:
            return []
        return [{"symbol": r[0], "direction": r[1], "confidence": r[2], "reasoning": r[3]} for r in rows]

    def normalize(self, raw: list[dict[str, Any]]) -> list[Event]:
        ts = datetime.now(tz=UTC)
        out: list[Event] = []
        for row in raw:
            payload = {
                "symbol": row["symbol"],
                "direction": row["direction"],
                "confidence": row["confidence"],
                "source": self.name,
                "reasoning": row.get("reasoning"),
            }
            out.append(
                self.draft_event(
                    event_type=EventType.SIGNAL_BENCHMARK_V1,
                    payload=payload,
                    ts=ts,
                    observed_at=ts,
                    source=self.name,
                    dedupe_key=_dedupe_key(self.name, row["symbol"], ts),
                )
            )
        return out
