"""engine.brain.data_quality

Data quality is not a gate. It is a gradient.

Missing or stale domains should *degrade gracefully*, not hard-fail the brain.
If a domain is stale, its weight is reduced for this cycle and then renormalized.

"Absence of data is also data. But not enough to trade on." (see EASTER_EGG_REFERENCE)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def quality_from_staleness(*, staleness_ms: int | None, expected_interval_ms: int) -> float:
    """Compute a 0..1 quality score from staleness.

    Rules (simple + stable):
    - missing -> 0
    - <= expected -> 1
    - expected..4*expected decays linearly to 0
    - >= 4*expected -> 0

    This mirrors the legacy monitor because it is easy to reason about.
    """

    if staleness_ms is None:
        return 0.0
    if expected_interval_ms <= 0:
        return 1.0

    s = max(0, int(staleness_ms))
    if s <= expected_interval_ms:
        return 1.0

    span = 3 * expected_interval_ms
    q = 1.0 - float(s - expected_interval_ms) / float(span)
    return _clamp01(q)


@dataclass(frozen=True, slots=True)
class DataQualityResult:
    as_of: datetime
    per_domain_staleness_ms: dict[str, int | None]
    per_domain_quality: dict[str, float]
    missing_domains: list[str]
    overall_quality: float

    def adjusted_weights(self, base_weights: dict[str, float]) -> dict[str, float]:
        """Down-weight base weights by quality and renormalize."""

        weighted: dict[str, float] = {}
        for dom, w in base_weights.items():
            q = float(self.per_domain_quality.get(dom, 1.0))
            weighted[dom] = float(w) * _clamp01(q)

        total = sum(weighted.values())
        if total <= 0:
            return dict(base_weights)
        return {k: float(v) / float(total) for k, v in weighted.items()}


class DataQualityMonitor:
    """Best-effort staleness monitor.

    We measure staleness from the latest event timestamps per domain.
    This keeps the monitor independent of any particular projection table.
    """

    # Default expected intervals (ms) per domain.
    EXPECTED_INTERVAL_MS: Final[dict[str, int]] = {
        "technical": 15 * 60 * 1000,
        "tradfi": 6 * 60 * 60 * 1000,
        "sentiment": 6 * 60 * 60 * 1000,
        "onchain": 6 * 60 * 60 * 1000,
        "events": 6 * 60 * 60 * 1000,
        "social": 6 * 60 * 60 * 1000,
        "curator": 24 * 60 * 60 * 1000,
    }

    DOMAIN_EVENT_TYPES: Final[dict[str, list[EventType]]] = {
        "technical": [EventType.SIGNAL_TA_V1, EventType.SIGNAL_ORDERBOOK_V1, EventType.SIGNAL_PRICE_ALERT_V1],
        "onchain": [EventType.SIGNAL_ONCHAIN_V1, EventType.SIGNAL_STABLECOIN_V1, EventType.SIGNAL_WHALE_V1],
        "tradfi": [EventType.SIGNAL_TRADFI_V1, EventType.SIGNAL_ETF_V1],
        "social": [EventType.SIGNAL_SOCIAL_V1, EventType.SIGNAL_SENTIMENT_V1, EventType.SIGNAL_ACI_V1],
        "events": [EventType.SIGNAL_EVENTS_V1],
        "curator": [EventType.SIGNAL_CURATOR_V1],
    }

    def __init__(self, config: Config, db: Database):
        self.config = config
        self.db = db

    def evaluate(
        self,
        *,
        as_of: datetime | None = None,
        domains: list[str] | None = None,
    ) -> DataQualityResult:
        now = as_of or datetime.now(tz=UTC)
        doms = domains or ["curator", "onchain", "tradfi", "social", "technical", "events"]

        staleness: dict[str, int | None] = {}
        quality: dict[str, float] = {}
        missing: list[str] = []

        for dom in doms:
            etypes = self.DOMAIN_EVENT_TYPES.get(dom, [])
            latest_ts: datetime | None = None
            for et in etypes:
                evs = self.db.get_events(event_type=et, limit=1)
                if not evs:
                    continue
                ts = evs[0].observed_at or evs[0].ts
                if latest_ts is None or ts > latest_ts:
                    latest_ts = ts

            if latest_ts is None:
                staleness[dom] = None
                missing.append(dom)
            else:
                staleness[dom] = int((now - latest_ts).total_seconds() * 1000)

            q = quality_from_staleness(
                staleness_ms=staleness[dom],
                expected_interval_ms=int(self.EXPECTED_INTERVAL_MS.get(dom, 0)),
            )
            quality[dom] = float(q)

        overall = float(sum(quality.values()) / len(quality)) if quality else 0.0
        return DataQualityResult(
            as_of=now,
            per_domain_staleness_ms=staleness,
            per_domain_quality=quality,
            missing_domains=missing,
            overall_quality=overall,
        )
