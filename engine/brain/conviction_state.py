"""engine.brain.conviction_state

Aggregated brain conviction state — safe cross-producer signal.

Exposes per-asset aggregate conviction as a single signed float:
positive = bullish, negative = bearish, near-zero = neutral/conflicted.

This is the ONLY information producers receive about other producers.
No identities, no domain breakdown, no individual confidence values.

Design:
- Reads recent FORECAST_V1 events from the DB
- Aggregates by asset: weighted average of (confidence × direction_sign)
- Direction sign: long=+1, short=-1, no_forecast=0
- Lookback window: configurable, default 2h
- Returns 0.0 (neutral) on any error or empty data
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from engine.core.events import EventType

logger = logging.getLogger(__name__)

# Direction sign mapping
_DIRECTION_SIGN: dict[str, float] = {
    "long": 1.0,
    "short": -1.0,
    "flat": 0.0,
    "no_forecast": 0.0,
}

DEFAULT_LOOKBACK_MINUTES = 120
MIN_FORECASTS_FOR_SIGNAL = 2
MAX_ROWS = 200


@dataclass(frozen=True, slots=True)
class ConvictionState:
    """Aggregate conviction for one asset."""

    asset: str
    conviction: float  # signed float: [-1, +1], positive=bullish
    forecast_count: int  # number of forecasts aggregated
    lookback_minutes: int


class ConvictionStateReader:
    """Reads aggregate conviction from recent FORECAST_V1 events.

    Designed to be instantiated once and queried per cycle.
    Fails silently — returns 0.0 on any error.
    """

    def __init__(self, db: Any, lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES) -> None:
        self.db = db
        self.lookback_minutes = lookback_minutes

    def get(self, asset: str) -> ConvictionState:
        """Return aggregate conviction for one asset. Never raises."""
        try:
            return self._query(asset)
        except Exception as exc:  # noqa: BLE001
            logger.debug("conviction_state_read_failed asset=%s error=%s", asset, exc)
            return ConvictionState(
                asset=asset,
                conviction=0.0,
                forecast_count=0,
                lookback_minutes=self.lookback_minutes,
            )

    @staticmethod
    def _connection(db: Any) -> Any:
        return getattr(db, "conn", db)

    @staticmethod
    def _decode_payload(raw: Any) -> dict[str, Any] | None:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                decoded = json.loads(raw)
            except Exception:  # noqa: BLE001
                return None
            return decoded if isinstance(decoded, dict) else None
        return None

    def _query(self, asset: str) -> ConvictionState:
        conn = self._connection(self.db)
        since_iso = (datetime.now(tz=UTC) - timedelta(minutes=self.lookback_minutes)).isoformat()

        rows = conn.execute(
            """
            SELECT payload
            FROM events
            WHERE type = ?
              AND ts >= ?
            ORDER BY ts DESC
            LIMIT ?
            """,
            (EventType.FORECAST_V1.value, since_iso, MAX_ROWS),
        ).fetchall()

        total_weight = 0.0
        weighted_sum = 0.0
        count = 0
        target_asset = str(asset).upper()

        for row in rows:
            payload = self._decode_payload(row[0])
            if payload is None:
                continue

            if str(payload.get("asset", "")).upper() != target_asset:
                continue

            action = str(payload.get("action", "no_forecast")).lower()
            sign = _DIRECTION_SIGN.get(action, 0.0)
            if sign == 0.0:
                continue

            try:
                confidence = float(payload.get("confidence", 0.0))
            except (TypeError, ValueError):
                continue

            weight = max(0.0, confidence)
            if weight == 0.0:
                continue

            weighted_sum += sign * weight
            total_weight += weight
            count += 1

        if count < MIN_FORECASTS_FOR_SIGNAL or total_weight == 0.0:
            return ConvictionState(
                asset=asset,
                conviction=0.0,
                forecast_count=count,
                lookback_minutes=self.lookback_minutes,
            )

        conviction = max(-1.0, min(1.0, weighted_sum / total_weight))
        return ConvictionState(
            asset=asset,
            conviction=round(conviction, 4),
            forecast_count=count,
            lookback_minutes=self.lookback_minutes,
        )
