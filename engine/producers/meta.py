"""engine.producers.meta

Meta-producer: learns from producer track-records only.

Hard constraint: no direct market data reads.
Inputs are restricted to:
- FORECAST_V1 (recent ensemble state)
- FORECAST_OUTCOME_V1 (historical outcomes)
- producer_performance / producer_correlation (derived tables)
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from engine.brain.performance_aggregator import PerformanceAggregator
from engine.core.database import Database
from engine.core.events import AbstentionReason, EventType, ForecastLifecycleState, ForecastPayload
from engine.core.forecast import abstain
from engine.core.types import ProducerHealth, ProducerResult
from engine.producers.base import BaseProducer, ProducerContext
from engine.producers.registry import register

logger = logging.getLogger(__name__)

MIN_FORECASTS_FOR_ACTIVATION = 500
MIN_SAMPLE_FOR_PATTERN = 10
WIN_RATE_THRESHOLD = 0.60


def _parse_iso_ts(value: str) -> float:
    normalized = str(value)
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).timestamp()


@register("meta", domain="events")
class MetaProducer(BaseProducer):
    """Ensemble pattern learner with activation gate and shadow mode."""

    producer_id = "meta"
    producer_version = "1.0.0"
    schedule = "*/30 * * * *"

    def __init__(self, ctx_or_db: ProducerContext | Database, shadow: bool = True):
        self.shadow = bool(shadow)
        self._ctx_mode = isinstance(ctx_or_db, ProducerContext)

        if self._ctx_mode:
            ctx = ctx_or_db  # type: ProducerContext
            super().__init__(ctx)
            self.db: Database = ctx.db
            self._log = ctx.logger
        else:
            assert isinstance(ctx_or_db, Database)
            self.db = ctx_or_db
            self._log = logger

        self._aggregator = PerformanceAggregator(self.db)

    def collect(self) -> list[dict]:
        # MetaProducer does not ingest raw external feeds.
        return []

    def normalize(self, raw: list[dict]) -> list[Any]:  # pragma: no cover - unused for meta producer
        return []

    def _source(self) -> str:
        return f"{self.name}@{self.producer_version}"

    def _is_active(self) -> bool:
        row = self.db.conn.execute(
            "SELECT COUNT(*) FROM events WHERE type = ?",
            (EventType.FORECAST_OUTCOME_V1.value,),
        ).fetchone()
        count = int(row[0] if row else 0)
        return count >= MIN_FORECASTS_FOR_ACTIVATION

    def _get_current_ensemble_state(self, asset: str) -> dict[str, str]:
        """Get latest long/short/flat action per producer for this asset (last 2h)."""

        asset_upper = str(asset).upper()
        cutoff_ts = float(datetime.now(tz=UTC).timestamp()) - (2 * 3600)

        rows = self.db.conn.execute(
            """
            SELECT source, ts, payload
            FROM events
            WHERE type = ?
            ORDER BY ts DESC
            LIMIT 5000
            """,
            (EventType.FORECAST_V1.value,),
        ).fetchall()

        state: dict[str, str] = {}
        for row in rows:
            try:
                ts_val = _parse_iso_ts(str(row["ts"]))
            except Exception:
                continue
            if ts_val < cutoff_ts:
                break

            payload = json.loads(str(row["payload"]))
            if str(payload.get("asset") or "").upper() != asset_upper:
                continue

            action = str(payload.get("action") or "").lower()
            if action not in {"long", "short", "flat"}:
                continue

            producer = str(row["source"] or payload.get("source") or "")
            producer = producer.split("@", 1)[0] if producer else ""
            if not producer or producer == self.name:
                continue

            if producer not in state:
                state[producer] = action

        return state

    def _find_matching_episodes(self, asset: str, ensemble_state: dict[str, str], horizon: str) -> list[dict]:
        """Find historical episodes with matching ensemble state."""

        if not ensemble_state:
            return []

        rows = self.db.conn.execute(
            """
            SELECT payload
            FROM events
            WHERE type = ?
            ORDER BY ts ASC
            """,
            (EventType.FORECAST_OUTCOME_V1.value,),
        ).fetchall()

        # episode key: 2h forecast timestamp bucket
        episodes: dict[int, dict[str, Any]] = defaultdict(lambda: {"actions": {}, "correct": {}, "actual_dir": "flat"})

        forecast_ts_cache: dict[str, float | None] = {}

        def _forecast_ts(event_id: str) -> float | None:
            if event_id in forecast_ts_cache:
                return forecast_ts_cache[event_id]
            row = self.db.conn.execute("SELECT ts FROM events WHERE id = ?", (event_id,)).fetchone()
            if row is None:
                forecast_ts_cache[event_id] = None
                return None
            try:
                val = _parse_iso_ts(str(row[0]))
            except Exception:
                forecast_ts_cache[event_id] = None
                return None
            forecast_ts_cache[event_id] = val
            return val

        for row in rows:
            try:
                payload = json.loads(str(row[0]))
            except Exception:
                continue

            if str(payload.get("asset") or "").upper() != str(asset).upper():
                continue
            if str(payload.get("horizon") or "") != str(horizon):
                continue

            producer = str(payload.get("producer_id") or "")
            action = str(payload.get("forecast_action") or "").lower()
            if not producer or action not in {"long", "short", "flat"}:
                continue

            fid = str(payload.get("forecast_event_id") or "")
            if not fid:
                continue

            fts = _forecast_ts(fid)
            if fts is None:
                continue
            bucket = int(fts // 7200)

            ep = episodes[bucket]
            ep["actions"][producer] = action
            ep["correct"][producer] = bool(payload.get("direction_correct"))

            ret = float(payload.get("return_actual_pct") or 0.0)
            if ret > 0:
                ep["actual_dir"] = "long"
            elif ret < 0:
                ep["actual_dir"] = "short"
            else:
                ep["actual_dir"] = "flat"

        matched: list[dict] = []
        for ep in episodes.values():
            actions = ep["actions"]
            if any(actions.get(prod) != act for prod, act in ensemble_state.items()):
                continue

            checks = [bool(ep["correct"][prod]) for prod in ensemble_state if prod in ep["correct"]]
            if not checks:
                continue

            matched.append(
                {
                    "direction_correct": (sum(1 for c in checks if c) / len(checks)) >= 0.5,
                    "actual_direction": str(ep.get("actual_dir") or "flat"),
                }
            )

        return matched

    def _compute_pattern_confidence(self, episodes: list[dict]) -> tuple[float, int]:
        """Returns (win_rate, n). Returns (0.0, 0) if insufficient data."""

        n = len(episodes)
        if n == 0:
            return 0.0, 0
        wins = sum(1 for ep in episodes if bool(ep.get("direction_correct")))
        return float(wins / n), int(n)

    def _majority_direction(self, episodes: list[dict]) -> str:
        winners = [str(ep.get("actual_direction") or "flat") for ep in episodes if bool(ep.get("direction_correct"))]
        pool = winners if winners else [str(ep.get("actual_direction") or "flat") for ep in episodes]
        counts = Counter(d for d in pool if d in {"long", "short", "flat"})
        if not counts:
            return "flat"
        top = counts.most_common()
        if len(top) > 1 and top[0][1] == top[1][1]:
            return "flat"
        return str(top[0][0])

    def produce(self, asset: str, horizon: str = "24h") -> ForecastPayload:
        """Main entry point."""

        # Keep rolling tables fresh each cycle (best-effort).
        try:
            self._aggregator.compute(window_days=90)
        except Exception:  # noqa: BLE001
            logger.debug("meta_producer_aggregator_compute_failed", exc_info=True)

        if not self._is_active():
            return abstain(
                source=self._source(),
                asset=asset,
                horizon=horizon,
                reason=AbstentionReason.INSUFFICIENT_DATA,
                regime_tag="unknown",
            )

        ensemble_state = self._get_current_ensemble_state(asset)
        if not ensemble_state:
            return abstain(
                source=self._source(),
                asset=asset,
                horizon=horizon,
                reason=AbstentionReason.INSUFFICIENT_DATA,
                regime_tag="unknown",
            )

        episodes = self._find_matching_episodes(asset, ensemble_state, horizon)
        win_rate, n = self._compute_pattern_confidence(episodes)

        if n < MIN_SAMPLE_FOR_PATTERN or win_rate < WIN_RATE_THRESHOLD:
            return abstain(
                source=self._source(),
                asset=asset,
                horizon=horizon,
                reason=AbstentionReason.LOW_CONFIDENCE,
                regime_tag="unknown",
            )

        direction = self._majority_direction(episodes)

        if self.shadow:
            self._log.info(
                "meta_producer_shadow asset=%s horizon=%s win_rate=%.4f n=%d direction=%s pattern=%s",
                asset,
                horizon,
                win_rate,
                n,
                direction,
                ensemble_state,
            )
            return abstain(
                source=self._source(),
                asset=asset,
                horizon=horizon,
                reason=AbstentionReason.SHADOW_MODE,
                regime_tag="unknown",
            )

        return ForecastPayload(
            forecast_id=str(uuid.uuid4()),
            asset=asset,
            horizon=horizon,
            action=direction,
            confidence=round(float(win_rate), 3),
            source=self._source(),
            regime_tag="unknown",
            lifecycle_state=ForecastLifecycleState.NEW,
            visible_signal_refs=[],
            used_signal_refs=[],
        )

    def _persist_forecast(self, forecast: ForecastPayload, *, asset: str, horizon: str) -> None:
        if self._ctx_mode:
            self._store_forecast(
                forecast=forecast,
                asset=asset,
                horizon=horizon,
                regime_tag=str(getattr(forecast, "regime_tag", "unknown") or "unknown"),
            )
            return

        # db-only mode (unit tests / direct usage)
        self.db.append_event(
            event_type=EventType.FORECAST_V1,
            payload=forecast.model_dump(mode="json"),
            source=self.name,
        )

    def run(self) -> ProducerResult:
        start = time.perf_counter()
        errors: list[str] = []
        published = 0
        health: ProducerHealth = ProducerHealth.OK

        try:
            assets = [str(s).upper() for s in getattr(self.ctx.config.universe, "symbols", [])] if self._ctx_mode else []
            for asset in assets:
                forecast = self.produce(asset=asset, horizon="24h")
                self._persist_forecast(forecast, asset=asset, horizon="24h")
                published += 1
        except Exception as e:  # noqa: BLE001
            errors.append(f"{type(e).__name__}: {e}")
            health = ProducerHealth.ERROR
            self._log.exception("meta_producer_run_failed")

        duration_ms = int((time.perf_counter() - start) * 1000)
        return ProducerResult(
            events_published=published,
            errors=errors,
            duration_ms=duration_ms,
            timestamp=datetime.now(tz=UTC),
            staleness_ms=None,
            health=health,
        )
