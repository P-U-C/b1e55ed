"""tests.mocks.mock_price_feed

MockPriceFeed — simulates real-world market conditions without touching
any live data source or API.

Capabilities:
- Accepts a scenario definition (asset, price series, timestamps)
- Built-in generators: trending_up, trending_down, ranging, crash, spike
- Price injection at specific times (for stop/target hit testing)
- Implements the same interface as PriceAlertsProducer (collect / normalize / run)
- Can insert price events directly into a Database instance
"""

from __future__ import annotations

import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

try:
    from datetime import UTC
except ImportError:
    UTC = UTC


# ──────────────────────────────────────────────────────────────────────────────
# Price-point dataclass
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PricePoint:
    symbol: str
    price: float
    ts: datetime
    bid: float | None = None
    ask: float | None = None
    volume: float | None = None


# ──────────────────────────────────────────────────────────────────────────────
# Scenario definition
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class PriceScenario:
    """Defines a named price scenario for a single asset."""

    symbol: str
    prices: list[float]  # ordered price series
    timestamps: list[datetime] | None = None  # optional explicit timestamps
    injections: dict[int, float] = field(default_factory=dict)  # {step_index: price}
    label: str = "custom"

    def __post_init__(self):
        if self.timestamps is not None:
            if len(self.timestamps) != len(self.prices):
                raise ValueError(f"timestamps length {len(self.timestamps)} != prices length {len(self.prices)}")

    def get_timestamps(self) -> list[datetime]:
        if self.timestamps is not None:
            return list(self.timestamps)
        base = datetime.now(tz=UTC)
        return [base + timedelta(minutes=i) for i in range(len(self.prices))]

    def as_price_points(self) -> list[PricePoint]:
        ts_list = self.get_timestamps()
        result: list[PricePoint] = []
        for i, (price, ts) in enumerate(zip(self.prices, ts_list, strict=False)):
            # Apply injection override if specified
            actual_price = self.injections.get(i, price)
            result.append(
                PricePoint(
                    symbol=self.symbol,
                    price=actual_price,
                    ts=ts,
                    bid=actual_price * 0.9995,
                    ask=actual_price * 1.0005,
                    volume=random.uniform(1_000_000, 10_000_000),
                )
            )
        return result


# ──────────────────────────────────────────────────────────────────────────────
# Scenario generators
# ──────────────────────────────────────────────────────────────────────────────


def trending_up(
    symbol: str,
    *,
    start: float = 100.0,
    steps: int = 20,
    pct_per_step: float = 0.01,
    noise: float = 0.002,
    seed: int | None = 42,
) -> PriceScenario:
    """Uptrend: each candle rises ~pct_per_step with small gaussian noise."""
    rng = random.Random(seed)
    prices = [start]
    for _ in range(steps - 1):
        drift = pct_per_step + rng.gauss(0, noise)
        prices.append(prices[-1] * (1.0 + drift))
    return PriceScenario(symbol=symbol, prices=prices, label="trending_up")


def trending_down(
    symbol: str,
    *,
    start: float = 100.0,
    steps: int = 20,
    pct_per_step: float = 0.01,
    noise: float = 0.002,
    seed: int | None = 42,
) -> PriceScenario:
    """Downtrend: each candle falls ~pct_per_step."""
    rng = random.Random(seed)
    prices = [start]
    for _ in range(steps - 1):
        drift = -pct_per_step + rng.gauss(0, noise)
        prices.append(prices[-1] * (1.0 + drift))
    return PriceScenario(symbol=symbol, prices=prices, label="trending_down")


def ranging(
    symbol: str,
    *,
    center: float = 100.0,
    amplitude: float = 2.0,
    steps: int = 20,
    seed: int | None = 42,
) -> PriceScenario:
    """Ranging market: price oscillates in a band around center."""
    rng = random.Random(seed)
    prices = [center + amplitude * math.sin(i * 0.5) + rng.gauss(0, amplitude * 0.1) for i in range(steps)]
    return PriceScenario(symbol=symbol, prices=prices, label="ranging")


def crash(
    symbol: str,
    *,
    start: float = 100.0,
    crash_step: int = 10,
    crash_pct: float = 0.20,
    steps: int = 20,
    seed: int | None = 42,
) -> PriceScenario:
    """Crash: stable then drops crash_pct at crash_step."""
    rng = random.Random(seed)
    prices = [start]
    for i in range(steps - 1):
        if i + 1 == crash_step:
            prices.append(prices[-1] * (1.0 - crash_pct))
        else:
            prices.append(prices[-1] * (1.0 + rng.gauss(0, 0.002)))
    return PriceScenario(symbol=symbol, prices=prices, label="crash")


def spike(
    symbol: str,
    *,
    start: float = 100.0,
    spike_step: int = 10,
    spike_pct: float = 0.15,
    steps: int = 20,
    seed: int | None = 42,
) -> PriceScenario:
    """Spike: stable then jumps spike_pct at spike_step, then returns."""
    rng = random.Random(seed)
    prices = [start]
    for i in range(steps - 1):
        if i + 1 == spike_step:
            prices.append(prices[-1] * (1.0 + spike_pct))
        elif i + 1 == spike_step + 1:
            prices.append(prices[-2])  # snap back
        else:
            prices.append(prices[-1] * (1.0 + rng.gauss(0, 0.002)))
    return PriceScenario(symbol=symbol, prices=prices, label="spike")


def inject_take_profit(scenario: PriceScenario, *, target_price: float, at_step: int) -> PriceScenario:
    """Return a copy of scenario with target_price injected at at_step."""
    injections = dict(scenario.injections)
    injections[at_step] = target_price
    return PriceScenario(
        symbol=scenario.symbol,
        prices=scenario.prices,
        timestamps=scenario.timestamps,
        injections=injections,
        label=f"{scenario.label}+tp@{at_step}",
    )


def inject_stop_loss(scenario: PriceScenario, *, stop_price: float, at_step: int) -> PriceScenario:
    """Return a copy of scenario with stop_price injected at at_step (for testing stop hits)."""
    injections = dict(scenario.injections)
    injections[at_step] = stop_price
    return PriceScenario(
        symbol=scenario.symbol,
        prices=scenario.prices,
        timestamps=scenario.timestamps,
        injections=injections,
        label=f"{scenario.label}+sl@{at_step}",
    )


# ──────────────────────────────────────────────────────────────────────────────
# MockPriceFeed — implements the Producer interface
# ──────────────────────────────────────────────────────────────────────────────


class MockPriceFeed:
    """Mock price feed that implements the same interface as PriceAlertsProducer.

    Usage::

        feed = MockPriceFeed(scenario)
        raw = feed.collect()
        events = feed.normalize(raw)
        feed.publish(events)          # or: feed.inject_into_db(db)
    """

    name = "mock-price-feed"
    domain = "technical"
    schedule = "*/1 * * * *"

    def __init__(
        self,
        scenario: PriceScenario,
        *,
        current_step: int = -1,  # -1 means last price
    ):
        self.scenario = scenario
        self._step = current_step

    @property
    def current_price(self) -> float:
        pts = self.scenario.as_price_points()
        if not pts:
            return 0.0
        idx = self._step if self._step >= 0 else len(pts) - 1
        idx = max(0, min(idx, len(pts) - 1))
        return pts[idx].price

    @property
    def latest_price_point(self) -> PricePoint:
        pts = self.scenario.as_price_points()
        idx = self._step if self._step >= 0 else len(pts) - 1
        idx = max(0, min(idx, len(pts) - 1))
        return pts[idx]

    def advance(self, steps: int = 1) -> MockPriceFeed:
        """Return a new feed advanced by `steps` steps."""
        pts = self.scenario.as_price_points()
        new_step = (self._step if self._step >= 0 else len(pts) - 1) + steps
        return MockPriceFeed(self.scenario, current_step=min(new_step, len(pts) - 1))

    # ── Producer interface ────────────────────────────────────────────────────

    def collect(self) -> list[dict[str, Any]]:
        """Return raw price data (matches PriceAlertsProducer.collect() shape)."""
        pp = self.latest_price_point
        return [
            {
                "symbol": pp.symbol,
                "price": pp.price,
                "bid": pp.bid,
                "ask": pp.ask,
                "venue": "mock",
                "data_source": "mock_price_feed",
                "ts": pp.ts.isoformat(),
            }
        ]

    def normalize(self, raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize raw records into event payloads for SIGNAL_PRICE_WS_V1."""
        result = []
        for r in raw:
            result.append(
                {
                    "id": str(uuid.uuid4()),
                    "type": "signal.price_ws.v1",
                    "ts": r.get("ts", datetime.now(tz=UTC).isoformat()),
                    "payload": {
                        "symbol": r["symbol"],
                        "price": r["price"],
                        "bid": r.get("bid"),
                        "ask": r.get("ask"),
                        "venue": r.get("venue", "mock"),
                        "data_source": r.get("data_source", "mock_price_feed"),
                    },
                }
            )
        return result

    def publish(self, events: list[dict[str, Any]]) -> int:
        return len(events)

    def run(self) -> dict[str, Any]:
        raw = self.collect()
        events = self.normalize(raw)
        n = self.publish(events)
        return {"events_published": n, "errors": [], "symbol": self.scenario.symbol}

    # ── DB injection helper ───────────────────────────────────────────────────

    def inject_into_db(self, db: Any, *, step: int | None = None) -> str:
        """Inject the current (or specified) price as a signal.price_ws.v1 event.

        Returns the event id.
        """
        from engine.core.events import EventType

        pts = self.scenario.as_price_points()
        if step is not None:
            idx = max(0, min(step, len(pts) - 1))
        else:
            idx = self._step if self._step >= 0 else len(pts) - 1
            idx = max(0, min(idx, len(pts) - 1))

        pp = pts[idx]
        event_id = db.append_event(
            event_type=EventType.SIGNAL_PRICE_WS_V1,
            payload={
                "symbol": pp.symbol,
                "price": pp.price,
                "bid": pp.bid,
                "ask": pp.ask,
                "venue": "mock",
                "data_source": "mock_price_feed",
            },
            source="mock.price_feed",
            ts=pp.ts,
        )
        return event_id

    def inject_all_into_db(self, db: Any) -> list[str]:
        """Inject all price points from the scenario into the DB."""
        from engine.core.events import EventType

        ids: list[str] = []
        for pp in self.scenario.as_price_points():
            event_id = db.append_event(
                event_type=EventType.SIGNAL_PRICE_WS_V1,
                payload={
                    "symbol": pp.symbol,
                    "price": pp.price,
                    "bid": pp.bid,
                    "ask": pp.ask,
                    "venue": "mock",
                    "data_source": "mock_price_feed",
                },
                source="mock.price_feed",
                ts=pp.ts,
            )
            ids.append(event_id)
        return ids
