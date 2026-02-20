from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

from engine.core.contributors import ContributorRegistry
from engine.core.database import Database


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    v = str(ts)
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class ContributorScore:
    contributor_id: str
    signals_submitted: int
    signals_accepted: int
    signals_profitable: int
    hit_rate: float
    avg_conviction: float
    total_karma_usd: float
    score: float
    last_active: str
    streak: int


class ContributorScoring:
    def __init__(self, db: Database):
        self._db = db
        self._registry = ContributorRegistry(db)

    def _streak_days(self, contributor_id: str) -> int:
        # Compute consecutive-day streak from contributor_signals.created_at.
        rows = self._db.conn.execute(
            """
            SELECT DISTINCT substr(created_at, 1, 10) as d
            FROM contributor_signals
            WHERE contributor_id = ?
            ORDER BY d DESC
            """,
            (contributor_id,),
        ).fetchall()
        if not rows:
            return 0

        days = [str(r[0]) for r in rows if r and r[0] is not None]
        if not days:
            return 0

        def to_date(s: str) -> datetime:
            return datetime.fromisoformat(s).replace(tzinfo=UTC)

        streak = 1
        prev = to_date(days[0])
        for d in days[1:]:
            cur = to_date(d)
            delta = (prev - cur).days
            if delta == 1:
                streak += 1
                prev = cur
                continue
            break
        return streak

    def compute_score(self, contributor_id: str) -> ContributorScore:
        # Aggregates
        row = self._db.conn.execute(
            """
            SELECT
                COUNT(1) as submitted,
                SUM(CASE WHEN accepted = 1 THEN 1 ELSE 0 END) as accepted,
                SUM(CASE WHEN profitable = 1 THEN 1 ELSE 0 END) as profitable,
                AVG(CASE WHEN signal_score IS NOT NULL THEN signal_score END) as avg_score,
                MAX(created_at) as last_active
            FROM contributor_signals
            WHERE contributor_id = ?
            """,
            (contributor_id,),
        ).fetchone()

        submitted = int(row[0] or 0)
        accepted = int(row[1] or 0)
        profitable = int(row[2] or 0)
        avg_conviction = float(row[3] or 0.0)
        last_active = str(row[4] or "")

        # hit rate
        hit_rate = float(profitable) / float(accepted) if accepted > 0 else 0.0

        # karma by node_id (best-effort)
        total_karma = 0.0
        contrib = self._registry.get(contributor_id)
        if contrib is not None:
            k_row = self._db.conn.execute(
                "SELECT SUM(karma_amount_usd) FROM karma_intents WHERE node_id = ?",
                (contrib.node_id,),
            ).fetchone()
            if k_row is not None and k_row[0] is not None:
                total_karma = float(k_row[0])

        streak = self._streak_days(contributor_id)

        # Composite components
        hit_rate_norm = _clamp01(hit_rate)

        # log-scaled volume (cap at ~100 submissions)
        volume_norm = 0.0
        if submitted > 0:
            volume_norm = _clamp01(math.log1p(float(submitted)) / math.log1p(100.0))

        consistency_norm = _clamp01(float(streak) / 30.0)

        # conviction accuracy: compare mean conviction for profitable vs unprofitable among accepted with known outcomes
        acc_row = self._db.conn.execute(
            """
            SELECT
                AVG(CASE WHEN profitable = 1 THEN signal_score END) as avg_win,
                AVG(CASE WHEN profitable = 0 THEN signal_score END) as avg_loss
            FROM contributor_signals
            WHERE contributor_id = ? AND accepted = 1 AND profitable IS NOT NULL AND signal_score IS NOT NULL
            """,
            (contributor_id,),
        ).fetchone()

        conviction_accuracy = 0.5
        if acc_row is not None and acc_row[0] is not None and acc_row[1] is not None:
            diff = float(acc_row[0]) - float(acc_row[1])
            # map diff to 0..1; assume score scale roughly 0..10
            conviction_accuracy = _clamp01(0.5 + diff / 20.0)

        # recency bonus
        recency = 0.0
        last_dt = _parse_iso(last_active)
        if last_dt is not None:
            days_since = max(0.0, (datetime.now(tz=UTC) - last_dt).total_seconds() / 86400.0)
            if days_since <= 7.0:
                recency = 1.0
            else:
                recency = _clamp01(1.0 - (days_since - 7.0) / 30.0)

        composite = 0.3 * hit_rate_norm + 0.25 * volume_norm + 0.2 * consistency_norm + 0.15 * conviction_accuracy + 0.1 * recency
        score_0_100 = 100.0 * _clamp01(composite)

        return ContributorScore(
            contributor_id=contributor_id,
            signals_submitted=submitted,
            signals_accepted=accepted,
            signals_profitable=profitable,
            hit_rate=hit_rate,
            avg_conviction=avg_conviction,
            total_karma_usd=total_karma,
            score=score_0_100,
            last_active=last_active,
            streak=streak,
        )

    def leaderboard(self, *, limit: int = 20) -> list[ContributorScore]:
        contributors = self._registry.list_all()
        scores = [self.compute_score(c.id) for c in contributors]
        scores.sort(key=lambda s: (s.score, s.signals_accepted, s.signals_submitted), reverse=True)
        return scores[: int(limit)]

    def update_outcomes(self, contributor_id: str, *, signal_id: str, profitable: bool) -> None:
        with self._db.conn:
            self._db.conn.execute(
                """
                UPDATE contributor_signals
                SET profitable = ?
                WHERE contributor_id = ? AND event_id = ?
                """,
                (1 if profitable else 0, contributor_id, signal_id),
            )
