"""engine.brain.outcome_resolver

Resolve FORECAST_V1 events into FORECAST_OUTCOME_V1 once horizon elapses.

Best-effort by design:
- never raises from a single-forecast failure
- idempotent via forecast_resolution_state + deterministic dedupe key
- prefers local price_history, falls back to Binance public klines API
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

import httpx

from engine.core.database import Database
from engine.core.events import EventType

logger = logging.getLogger(__name__)

_RESOLUTION_BUFFER_SECONDS = 5 * 60
_PRICE_TOLERANCE_SECONDS = 30 * 60


@dataclass(frozen=True, slots=True)
class ForecastOutcomePayload:
    forecast_event_id: str
    producer_id: str
    asset: str
    horizon: str
    forecast_action: str
    forecast_confidence: float
    forecast_price: float
    actual_price: float
    return_actual_pct: float
    direction_correct: bool
    brier_score: float
    regime_at_forecast: str
    resolved_at: float


def _parse_horizon_seconds(label: str) -> int | None:
    m = re.fullmatch(r"\s*(\d+)\s*([mhd])\s*", str(label).strip().lower())
    if not m:
        return None
    qty = int(m.group(1))
    unit = m.group(2)
    if unit == "m":
        return qty * 60
    if unit == "h":
        return qty * 3600
    if unit == "d":
        return qty * 86400
    return None


def _parse_iso_ts(value: str) -> float:
    normalized = str(value)
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).timestamp()


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _binance_symbol(asset: str) -> str:
    raw = re.sub(r"[^A-Z0-9]", "", str(asset).upper())
    if raw.endswith("USDT"):
        return raw
    if raw.endswith("USD"):
        raw = raw[:-3]
    if raw.endswith("PERP"):
        raw = raw[:-4]
    return f"{raw}USDT"


class OutcomeResolver:
    def __init__(self, db: Database):
        self.db = db
        self.last_skipped_missing_price = 0

    def resolve_pending(self, now: datetime | None = None) -> int:
        """Resolve all eligible unresolved forecasts. Returns count resolved."""

        now_utc = now or datetime.now(tz=UTC)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=UTC)

        before_ts = now_utc.timestamp() - _RESOLUTION_BUFFER_SECONDS
        resolved = 0
        skipped_missing_price = 0

        for forecast in self._find_unresolved(before_ts):
            forecast_event_id = str(forecast.get("event_id") or "")
            try:
                forecast_price = self._fetch_actual_price(str(forecast["asset"]), float(forecast["forecast_ts"]))
                actual_price = self._fetch_actual_price(str(forecast["asset"]), float(forecast["target_ts"]))
                if forecast_price is None or actual_price is None:
                    skipped_missing_price += 1
                    logger.warning(
                        "outcome_resolver_missing_price",
                        extra={
                            "forecast_event_id": forecast_event_id,
                            "asset": forecast.get("asset"),
                            "target_ts": forecast.get("target_ts"),
                        },
                    )
                    continue

                forecast_with_prices = dict(forecast)
                forecast_with_prices["forecast_price"] = float(forecast_price)
                outcome = self._compute_outcome(forecast_with_prices, float(actual_price))
                outcome_event_id = self._write_outcome(outcome)

                with self.db.conn:
                    self.db.conn.execute(
                        """
                        INSERT OR IGNORE INTO forecast_resolution_state
                            (forecast_event_id, resolved_at, outcome_event_id)
                        VALUES (?, ?, ?)
                        """,
                        (outcome.forecast_event_id, outcome.resolved_at, outcome_event_id),
                    )
                resolved += 1
            except Exception:  # noqa: BLE001
                logger.exception("outcome_resolver_forecast_failed", extra={"forecast_event_id": forecast_event_id})
                continue

        self.last_skipped_missing_price = skipped_missing_price
        return resolved

    def _find_unresolved(self, before_ts: float) -> list[dict]:
        """Find FORECAST_V1 events not yet in forecast_resolution_state."""

        rows = self.db.conn.execute(
            """
            SELECT e.id, e.ts, e.source, e.payload
            FROM events e
            LEFT JOIN forecast_resolution_state rs ON rs.forecast_event_id = e.id
            WHERE e.type = ?
              AND rs.forecast_event_id IS NULL
            ORDER BY e.ts ASC
            """,
            (EventType.FORECAST_V1.value,),
        ).fetchall()

        out: list[dict] = []
        for row in rows:
            payload = json.loads(str(row["payload"]))

            action = str(payload.get("action") or "").lower()
            if action not in {"long", "short", "flat"}:
                continue

            horizon = str(payload.get("horizon") or "")
            horizon_seconds = _parse_horizon_seconds(horizon)
            if horizon_seconds is None:
                continue

            forecast_ts = _parse_iso_ts(str(row["ts"]))
            target_ts = forecast_ts + float(horizon_seconds)
            if target_ts > before_ts:
                continue

            asset = str(payload.get("asset") or payload.get("symbol") or "").upper().strip()
            if not asset:
                continue

            source = str(payload.get("source") or row["source"] or "")
            producer_id = source.split("@", 1)[0] if source else str(row["source"] or "unknown")

            out.append(
                {
                    "event_id": str(row["id"]),
                    "asset": asset,
                    "horizon": horizon,
                    "forecast_action": action,
                    "forecast_confidence": _as_float(payload.get("confidence"), 0.0),
                    "regime_at_forecast": str(payload.get("regime_tag") or "unknown"),
                    "producer_id": producer_id,
                    "forecast_ts": forecast_ts,
                    "target_ts": target_ts,
                }
            )

        return out

    def _fetch_actual_price(self, asset: str, target_ts: float) -> float | None:
        """Fetch actual close price at target timestamp. Returns None on failure."""

        # 1) Local DB first (seconds epoch)
        local_price = self._fetch_from_price_history(asset=asset, target_ts=target_ts, as_millis=False)
        if local_price is not None:
            return local_price

        # 2) Local DB fallback (milliseconds epoch)
        local_price_ms = self._fetch_from_price_history(asset=asset, target_ts=target_ts, as_millis=True)
        if local_price_ms is not None:
            return local_price_ms

        # 3) Binance fallback
        symbol = _binance_symbol(asset)
        params = {
            "symbol": symbol,
            "interval": "1h",
            "startTime": int(target_ts * 1000),
            "limit": 1,
        }
        try:
            response = httpx.get("https://api.binance.com/api/v3/klines", params=params, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list) and data and isinstance(data[0], list) and len(data[0]) >= 5:
                return float(data[0][4])
        except Exception:  # noqa: BLE001
            logger.debug("outcome_resolver_binance_fetch_failed", exc_info=True)
        return None

    def _fetch_from_price_history(self, *, asset: str, target_ts: float, as_millis: bool) -> float | None:
        try:
            cols = {str(r["name"] if isinstance(r, dict) else r[1]) for r in self.db.conn.execute("PRAGMA table_info(price_history)").fetchall()}
        except Exception:
            return None

        if not cols:
            return None

        price_col = next((c for c in ("close", "price", "close_price") if c in cols), None)
        time_col = next((c for c in ("ts", "timestamp", "time", "close_time") if c in cols), None)
        asset_col = next((c for c in ("asset", "symbol") if c in cols), None)
        if price_col is None or time_col is None or asset_col is None:
            return None

        base = re.sub(r"[^A-Z0-9]", "", str(asset).upper())
        base = base[:-4] if base.endswith("USDT") else base
        asset_a = base
        asset_b = f"{base}USDT"

        ts_value = float(target_ts * 1000.0) if as_millis else float(target_ts)
        tol = float(_PRICE_TOLERANCE_SECONDS * (1000 if as_millis else 1))
        low = ts_value - tol
        high = ts_value + tol

        try:
            row = self.db.conn.execute(
                f"""
                SELECT {price_col} AS close_price, ABS({time_col} - ?) AS delta
                FROM price_history
                WHERE UPPER({asset_col}) IN (?, ?)
                  AND {time_col} BETWEEN ? AND ?
                ORDER BY delta ASC
                LIMIT 1
                """,
                (ts_value, asset_a, asset_b, low, high),
            ).fetchone()
            if row is None:
                return None
            return float(row[0])
        except Exception:
            return None

    def _compute_outcome(self, forecast: dict, actual_price: float) -> ForecastOutcomePayload:
        forecast_price = _as_float(forecast.get("forecast_price"), 0.0)
        if forecast_price <= 0:
            raise ValueError("missing forecast_price")

        action = str(forecast.get("forecast_action") or "flat").lower()
        confidence = _as_float(forecast.get("forecast_confidence"), 0.0)

        return_actual_pct = ((float(actual_price) - forecast_price) / forecast_price) * 100.0
        if action == "long":
            direction_correct = float(actual_price) > forecast_price
        elif action == "short":
            direction_correct = float(actual_price) < forecast_price
        else:  # flat
            direction_correct = abs(return_actual_pct) < 0.000001

        outcome_binary = 1.0 if direction_correct else 0.0
        brier = (confidence - outcome_binary) ** 2

        return ForecastOutcomePayload(
            forecast_event_id=str(forecast["event_id"]),
            producer_id=str(forecast.get("producer_id") or "unknown"),
            asset=str(forecast["asset"]),
            horizon=str(forecast["horizon"]),
            forecast_action=action,
            forecast_confidence=confidence,
            forecast_price=float(forecast_price),
            actual_price=float(actual_price),
            return_actual_pct=float(return_actual_pct),
            direction_correct=bool(direction_correct),
            brier_score=float(brier),
            regime_at_forecast=str(forecast.get("regime_at_forecast") or "unknown"),
            resolved_at=float(datetime.now(tz=UTC).timestamp()),
        )

    def _write_outcome(self, outcome: ForecastOutcomePayload) -> str:
        """Write FORECAST_OUTCOME_V1 event. Returns event_id."""

        event = self.db.append_event(
            event_type=EventType.FORECAST_OUTCOME_V1,
            payload=asdict(outcome),
            source="brain.outcome_resolver",
            dedupe_key=f"{EventType.FORECAST_OUTCOME_V1.value}:{outcome.forecast_event_id}",
        )
        return str(event.id)


def run_resolver(db: Database) -> int:
    """Convenience entry point for cron/CLI. Returns count of resolved forecasts."""

    resolver = OutcomeResolver(db)
    return resolver.resolve_pending()
