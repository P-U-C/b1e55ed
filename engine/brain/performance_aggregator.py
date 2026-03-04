"""engine.brain.performance_aggregator

Compute rolling producer performance from FORECAST_OUTCOME_V1 history.

Best-effort by design:
- compute() never raises
- missing/partial data returns an empty summary
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime
from itertools import combinations

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from engine.core.database import Database
from engine.core.events import EventType

logger = logging.getLogger(__name__)


def _parse_iso_ts(value: str) -> float:
    normalized = str(value)
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).timestamp()


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return float(sum(values) / len(values))


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mx = _mean(xs)
    my = _mean(ys)
    if mx is None or my is None:
        return None

    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    var_x = sum(v * v for v in dx)
    var_y = sum(v * v for v in dy)
    if var_x <= 0.0 or var_y <= 0.0:
        return None

    cov = sum(a * b for a, b in zip(dx, dy, strict=True))
    return float(cov / ((var_x**0.5) * (var_y**0.5)))


class PerformanceAggregator:
    MIN_FORECASTS_FOR_STATS = 5

    def __init__(self, db: Database):
        self.db = db

    def compute(self, window_days: int = 90, now: datetime | None = None) -> dict:
        """Compute all stats. Returns summary dict. Best-effort, never raises."""

        now_utc = now or datetime.now(tz=UTC)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=UTC)

        computed_at = float(now_utc.timestamp())
        since_ts = computed_at - float(max(int(window_days), 1) * 86400)

        try:
            outcomes = self._load_outcomes(since_ts=since_ts)
            if not outcomes:
                return {
                    "computed_at": computed_at,
                    "window_days": int(window_days),
                    "outcome_count": 0,
                    "producer_rows": 0,
                    "correlation_rows": 0,
                }

            producer_rows = self._compute_producer_stats(
                outcomes=outcomes,
                computed_at=computed_at,
                window_days=int(window_days),
            )
            correlation_rows = self._compute_correlations(
                outcomes=outcomes,
                computed_at=computed_at,
                window_days=int(window_days),
            )

            return {
                "computed_at": computed_at,
                "window_days": int(window_days),
                "outcome_count": len(outcomes),
                "producer_rows": producer_rows,
                "correlation_rows": correlation_rows,
            }
        except Exception:  # noqa: BLE001
            logger.exception("performance_aggregator_compute_failed")
            return {
                "computed_at": computed_at,
                "window_days": int(window_days),
                "outcome_count": 0,
                "producer_rows": 0,
                "correlation_rows": 0,
            }

    def get_producer_stats(self, producer_id: str, asset: str, horizon: str, regime: str = "all") -> dict | None:
        """Read latest stats for one producer. Returns None if insufficient data."""

        row = self.db.conn.execute(
            """
            SELECT computed_at, producer_id, asset, horizon, regime, window_days,
                   forecast_count, win_rate, avg_brier, avg_confidence, confidence_reliability
            FROM producer_performance
            WHERE producer_id = ?
              AND asset = ?
              AND horizon = ?
              AND regime = ?
            ORDER BY computed_at DESC, id DESC
            LIMIT 1
            """,
            (str(producer_id), str(asset).upper(), str(horizon), str(regime)),
        ).fetchone()
        if row is None:
            return None

        out = {
            "computed_at": float(row[0]),
            "producer_id": str(row[1]),
            "asset": str(row[2]),
            "horizon": str(row[3]),
            "regime": str(row[4]),
            "window_days": int(row[5]),
            "forecast_count": int(row[6]),
            "win_rate": None if row[7] is None else float(row[7]),
            "avg_brier": None if row[8] is None else float(row[8]),
            "avg_confidence": None if row[9] is None else float(row[9]),
            "confidence_reliability": None if row[10] is None else float(row[10]),
        }
        forecast_count: int = int(str(out["forecast_count"]))
        if forecast_count < self.MIN_FORECASTS_FOR_STATS:
            return None
        return out

    def get_correlation_matrix(self, asset: str, horizon: str) -> dict:
        """Read latest pairwise producer correlations."""

        latest = self.db.conn.execute(
            """
            SELECT MAX(computed_at)
            FROM producer_correlation
            WHERE asset = ?
              AND horizon = ?
            """,
            (str(asset).upper(), str(horizon)),
        ).fetchone()
        latest_ts = None if latest is None else latest[0]
        if latest_ts is None:
            return {"asset": str(asset).upper(), "horizon": str(horizon), "computed_at": None, "pairs": []}

        rows = self.db.conn.execute(
            """
            SELECT producer_a, producer_b, agreement_rate,
                   agreement_win_rate, disagreement_win_rate_a, sample_count
            FROM producer_correlation
            WHERE asset = ?
              AND horizon = ?
              AND computed_at = ?
            ORDER BY producer_a ASC, producer_b ASC
            """,
            (str(asset).upper(), str(horizon), float(latest_ts)),
        ).fetchall()

        pairs = [
            {
                "producer_a": str(r[0]),
                "producer_b": str(r[1]),
                "agreement_rate": None if r[2] is None else float(r[2]),
                "agreement_win_rate": None if r[3] is None else float(r[3]),
                "disagreement_win_rate_a": None if r[4] is None else float(r[4]),
                "sample_count": int(r[5]),
            }
            for r in rows
        ]

        return {
            "asset": str(asset).upper(),
            "horizon": str(horizon),
            "computed_at": float(latest_ts),
            "pairs": pairs,
        }

    def _load_outcomes(self, *, since_ts: float) -> list[dict]:
        rows = self.db.conn.execute(
            """
            SELECT ts, payload
            FROM events
            WHERE type = ?
            ORDER BY ts ASC
            """,
            (EventType.FORECAST_OUTCOME_V1.value,),
        ).fetchall()

        outcomes: list[dict] = []
        for row in rows:
            try:
                event_ts = _parse_iso_ts(str(row[0]))
                if event_ts < since_ts:
                    continue
                payload = json.loads(str(row[1]))
                payload["_event_ts"] = event_ts
                payload["asset"] = str(payload.get("asset") or "").upper()
                payload["horizon"] = str(payload.get("horizon") or "")
                payload["producer_id"] = str(payload.get("producer_id") or "")
                payload["regime_at_forecast"] = str(payload.get("regime_at_forecast") or "unknown")
                outcomes.append(payload)
            except Exception:  # noqa: BLE001
                continue
        return outcomes

    def _compute_producer_stats(self, *, outcomes: list[dict], computed_at: float, window_days: int) -> int:
        grouped: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)

        for out in outcomes:
            producer_id = str(out.get("producer_id") or "")
            asset = str(out.get("asset") or "").upper()
            horizon = str(out.get("horizon") or "")
            regime = str(out.get("regime_at_forecast") or "unknown")
            if not producer_id or not asset or not horizon:
                continue

            grouped[(producer_id, asset, horizon, regime)].append(out)
            grouped[(producer_id, asset, horizon, "all")].append(out)

        inserted = 0
        with self.db.conn:
            for (producer_id, asset, horizon, regime), rows in grouped.items():
                n = len(rows)
                wins = sum(1 for r in rows if bool(r.get("direction_correct")))
                win_rate = None
                if n >= self.MIN_FORECASTS_FOR_STATS:
                    win_rate = float(wins / n)

                briers = [float(r.get("brier_score") or 0.0) for r in rows]
                confidences = [float(r.get("forecast_confidence") or 0.0) for r in rows]
                outcomes_bin = [1.0 if bool(r.get("direction_correct")) else 0.0 for r in rows]

                avg_brier = _mean(briers)
                avg_conf = _mean(confidences)
                reliability = _pearson(confidences, outcomes_bin)

                self.db.conn.execute(
                    """
                    INSERT INTO producer_performance (
                        computed_at, producer_id, asset, horizon, regime,
                        window_days, forecast_count, win_rate, avg_brier,
                        avg_confidence, confidence_reliability
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        float(computed_at),
                        producer_id,
                        asset,
                        horizon,
                        regime,
                        int(window_days),
                        int(n),
                        win_rate,
                        avg_brier,
                        avg_conf,
                        reliability,
                    ),
                )
                inserted += 1

        return inserted

    def _compute_correlations(self, *, outcomes: list[dict], computed_at: float, window_days: int) -> int:
        forecast_ts_cache: dict[str, float | None] = {}

        def _forecast_ts(event_id: str) -> float | None:
            if event_id in forecast_ts_cache:
                return forecast_ts_cache[event_id]
            row = self.db.conn.execute("SELECT ts FROM events WHERE id = ?", (event_id,)).fetchone()
            if row is None:
                forecast_ts_cache[event_id] = None
                return None
            try:
                ts_val = _parse_iso_ts(str(row[0]))
            except Exception:
                forecast_ts_cache[event_id] = None
                return None
            forecast_ts_cache[event_id] = ts_val
            return ts_val

        episodes: dict[tuple[str, str, int], dict[str, dict]] = defaultdict(dict)

        for out in outcomes:
            fid = str(out.get("forecast_event_id") or "")
            producer = str(out.get("producer_id") or "")
            asset = str(out.get("asset") or "").upper()
            horizon = str(out.get("horizon") or "")
            action = str(out.get("forecast_action") or "").lower()
            if not fid or not producer or not asset or not horizon or action not in {"long", "short", "flat"}:
                continue

            ts_val = _forecast_ts(fid)
            if ts_val is None:
                continue

            # 2h bins align with MetaProducer ensemble lookback semantics.
            bucket = int(ts_val // 7200)
            key = (asset, horizon, bucket)
            episodes[key][producer] = {
                "action": action,
                "direction_correct": bool(out.get("direction_correct")),
            }

        # Group episode keys by (asset, horizon)
        by_market: dict[tuple[str, str], list[dict[str, dict]]] = defaultdict(list)
        for (asset, horizon, _bucket), episode in episodes.items():
            by_market[(asset, horizon)].append(episode)

        inserted = 0
        with self.db.conn:
            for (asset, horizon), market_episodes in by_market.items():
                producers = sorted({p for ep in market_episodes for p in ep})
                for producer_a, producer_b in combinations(producers, 2):
                    sample_count = 0
                    agree_count = 0
                    agree_wins = 0
                    disagree_count = 0
                    disagree_wins_a = 0

                    for ep in market_episodes:
                        if producer_a not in ep or producer_b not in ep:
                            continue
                        sample_count += 1

                        a_action = str(ep[producer_a].get("action") or "")
                        b_action = str(ep[producer_b].get("action") or "")
                        a_correct = bool(ep[producer_a].get("direction_correct"))

                        if a_action == b_action:
                            agree_count += 1
                            if a_correct:
                                agree_wins += 1
                        else:
                            disagree_count += 1
                            if a_correct:
                                disagree_wins_a += 1

                    if sample_count == 0:
                        continue

                    agreement_rate = float(agree_count / sample_count)
                    agreement_win_rate = None if agree_count == 0 else float(agree_wins / agree_count)
                    disagreement_win_rate_a = None if disagree_count == 0 else float(disagree_wins_a / disagree_count)

                    # Backwards-compatible upsert against legacy UNIQUE(producer_a, producer_b, asset, regime).
                    self.db.conn.execute(
                        """
                        INSERT INTO producer_correlation (
                            computed_at, producer_a, producer_b, asset, horizon, regime,
                            agreement_rate, agreement_win_rate, disagreement_win_rate_a,
                            sample_count, window_days, last_updated
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                        ON CONFLICT(producer_a, producer_b, asset, regime)
                        DO UPDATE SET
                            computed_at = excluded.computed_at,
                            horizon = excluded.horizon,
                            agreement_rate = excluded.agreement_rate,
                            agreement_win_rate = excluded.agreement_win_rate,
                            disagreement_win_rate_a = excluded.disagreement_win_rate_a,
                            sample_count = excluded.sample_count,
                            window_days = excluded.window_days,
                            last_updated = excluded.last_updated
                        """,
                        (
                            float(computed_at),
                            producer_a,
                            producer_b,
                            asset,
                            horizon,
                            horizon,  # encode horizon into legacy UNIQUE(regime) column
                            agreement_rate,
                            agreement_win_rate,
                            disagreement_win_rate_a,
                            int(sample_count),
                            int(window_days),
                        ),
                    )
                    inserted += 1

        return inserted
