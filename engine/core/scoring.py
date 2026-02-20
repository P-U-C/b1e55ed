"""engine.core.scoring

Contributor reputation scoring — calibrated, anti-gaming.

Review findings addressed (S1):
- Volume weights accepted signals, not submitted (close gaming vector)
- Streak counts accepted-signal days only (prevent drip farming)
- Hit rate requires minimum resolved outcomes before counting
- Penalty for consistently wrong signals (< 20% hit rate)
- Brier score for calibration quality
- Acceptance rate gate (< 10% = scored as zero)

Composite weights:
  0.35 * hit_rate        (hardest to game, highest weight)
  0.20 * calibration     (Brier score quality)
  0.20 * volume          (accepted signals, log-scaled)
  0.15 * consistency     (sqrt-scaled streak of accepted-signal days)
  0.10 * recency
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

from engine.core.contributors import ContributorRegistry
from engine.core.database import Database

# Minimum resolved outcomes before hit rate counts
MIN_RESOLVED_FOR_HIT_RATE = 5
# Below this acceptance rate, contributor scores zero
MIN_ACCEPTANCE_RATE = 0.10


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
    signals_resolved: int  # accepted with known outcome (profitable is not null)
    hit_rate: float
    acceptance_rate: float
    brier_score: float  # lower is better; 0 = perfect calibration
    avg_conviction: float
    total_karma_usd: float
    score: float
    last_active: str
    streak: int


class ContributorScoring:
    def __init__(self, db: Database):
        self._db = db
        self._registry = ContributorRegistry(db)

    def _accepted_streak_days(self, contributor_id: str) -> int:
        """Consecutive days with at least one ACCEPTED signal."""
        rows = self._db.conn.execute(
            """
            SELECT DISTINCT substr(created_at, 1, 10) as d
            FROM contributor_signals
            WHERE contributor_id = ? AND accepted = 1
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

    def _brier_score(self, contributor_id: str) -> float:
        """Compute Brier score for calibration quality.

        Brier = mean((confidence - outcome)^2) where:
        - confidence = signal_score / 10 (normalized to 0-1)
        - outcome = 1 if profitable, 0 if not

        Lower is better. 0.25 = random baseline. < 0.25 = better than random.
        Returns 0.25 (neutral) if insufficient data.
        """
        rows = self._db.conn.execute(
            """
            SELECT signal_score, profitable
            FROM contributor_signals
            WHERE contributor_id = ? AND accepted = 1
              AND profitable IS NOT NULL AND signal_score IS NOT NULL
            """,
            (contributor_id,),
        ).fetchall()

        if len(rows) < MIN_RESOLVED_FOR_HIT_RATE:
            return 0.25  # neutral

        total = 0.0
        for r in rows:
            confidence = _clamp01(float(r[0]) / 10.0)
            outcome = 1.0 if int(r[1]) == 1 else 0.0
            total += (confidence - outcome) ** 2

        return total / len(rows)

    def compute_score(self, contributor_id: str) -> ContributorScore:
        row = self._db.conn.execute(
            """
            SELECT
                COUNT(1) as submitted,
                SUM(CASE WHEN accepted = 1 THEN 1 ELSE 0 END) as accepted,
                SUM(CASE WHEN profitable = 1 THEN 1 ELSE 0 END) as profitable,
                SUM(CASE WHEN accepted = 1 AND profitable IS NOT NULL THEN 1 ELSE 0 END) as resolved,
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
        resolved = int(row[3] or 0)
        avg_conviction = float(row[4] or 0.0)
        last_active = str(row[5] or "")

        # Acceptance rate gate
        acceptance_rate = float(accepted) / float(submitted) if submitted > 0 else 0.0
        if acceptance_rate < MIN_ACCEPTANCE_RATE and submitted >= 10:
            # Below 10% acceptance with 10+ signals = noise contributor
            return ContributorScore(
                contributor_id=contributor_id,
                signals_submitted=submitted,
                signals_accepted=accepted,
                signals_profitable=profitable,
                signals_resolved=resolved,
                hit_rate=0.0,
                acceptance_rate=acceptance_rate,
                brier_score=0.25,
                avg_conviction=avg_conviction,
                total_karma_usd=0.0,
                score=0.0,
                last_active=last_active,
                streak=0,
            )

        # Hit rate: profitable / resolved (not profitable / accepted)
        # Only count if enough resolved outcomes exist
        if resolved >= MIN_RESOLVED_FOR_HIT_RATE:
            hit_rate = float(profitable) / float(resolved)
        else:
            hit_rate = 0.0  # Insufficient data, not penalized but not rewarded

        # Penalty for consistently wrong (< 20% hit rate with enough data)
        hit_rate_norm = _clamp01(hit_rate)
        if resolved >= MIN_RESOLVED_FOR_HIT_RATE and hit_rate < 0.20:
            # Negative contribution: actively harmful signals
            hit_rate_norm = -0.1 * (0.20 - hit_rate) / 0.20  # scales from 0 to -0.1

        # Brier score (calibration quality)
        brier = self._brier_score(contributor_id)
        # Convert to 0-1 where 1 = perfect calibration
        # 0.0 brier = 1.0 score, 0.25 brier (random) = 0.0 score, >0.25 = negative
        calibration_norm = _clamp01(1.0 - brier / 0.25)

        # Volume: accepted signals (not submitted!)
        volume_norm = 0.0
        if accepted > 0:
            volume_norm = _clamp01(math.log1p(float(accepted)) / math.log1p(100.0))

        # Consistency: sqrt-scaled streak of accepted-signal days
        # sqrt gives diminishing returns (day 9→10 worth less than day 1→2)
        streak = self._accepted_streak_days(contributor_id)
        consistency_norm = _clamp01(math.sqrt(float(streak)) / math.sqrt(30.0))

        # Recency bonus
        recency = 0.0
        last_dt = _parse_iso(last_active)
        if last_dt is not None:
            days_since = max(0.0, (datetime.now(tz=UTC) - last_dt).total_seconds() / 86400.0)
            if days_since <= 7.0:
                recency = 1.0
            else:
                recency = _clamp01(1.0 - (days_since - 7.0) / 30.0)

        # Karma
        total_karma = 0.0
        contrib = self._registry.get(contributor_id)
        if contrib is not None:
            k_row = self._db.conn.execute(
                "SELECT SUM(karma_amount_usd) FROM karma_intents WHERE node_id = ?",
                (contrib.node_id,),
            ).fetchone()
            if k_row is not None and k_row[0] is not None:
                total_karma = float(k_row[0])

        # Composite: hardest-to-game components get highest weight
        composite = (
            0.35 * hit_rate_norm
            + 0.20 * calibration_norm
            + 0.20 * volume_norm
            + 0.15 * consistency_norm
            + 0.10 * recency
        )
        score_0_100 = 100.0 * _clamp01(composite)

        return ContributorScore(
            contributor_id=contributor_id,
            signals_submitted=submitted,
            signals_accepted=accepted,
            signals_profitable=profitable,
            signals_resolved=resolved,
            hit_rate=hit_rate,
            acceptance_rate=acceptance_rate,
            brier_score=brier,
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
