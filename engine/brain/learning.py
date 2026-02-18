"""engine.brain.learning

The system that learns from its own outcomes will outperform systems that don't.

This module implements b1e55ed's compound learning loop:
1) Outcome attribution — match closed positions to the conviction that opened them
2) Weight adjustment — nudge synthesis domain weights based on performance
3) Producer scoring — track producer-level accuracy and reliability
4) Corpus feedback — score patterns/skills based on realized outcomes

Cold start:
- First 30 days: observe only. "Patience is not inaction. It is intelligent waiting."
- 30-90 days: warm period, half-sized adjustments (±1%).
- 90+ days: full learning loop active (±2%).

Overfitting protection:
"The market rewards adaptation. It punishes curve-fitting."
If 3 consecutive cycles degrade performance, revert.
"Sometimes the wisest adjustment is to undo the last one."
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType
from engine.core.time import utc_now
from engine.core.types import (
    CorpusFeedback,
    LearningResult,
    OutcomeAttribution,
    ProducerScore,
    WeightAdjustment,
)


@dataclass
class LearningLoop:
    """The compound learning engine."""

    db: Database
    config: Config

    # Safety constraints (SDD / task spec)
    ADJUSTMENT_WINDOW_DAYS: int = 30
    MIN_OBSERVATIONS: int = 20
    MAX_WEIGHT_DELTA: float = 0.02  # ±2% per cycle
    MIN_DOMAIN_WEIGHT: float = 0.05
    MAX_DOMAIN_WEIGHT: float = 0.40
    REVERSION_THRESHOLD: int = 3

    def _data_path(self, name: str) -> Path:
        p = Path(self.config.data_dir) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    # ---------------------------------------------------------------------
    # 1) Outcome attribution
    # ---------------------------------------------------------------------

    def attribute_outcome(self, position_id: str, realized_pnl: float) -> OutcomeAttribution:
        row = self.db.conn.execute(
            "SELECT * FROM positions WHERE id = ?",
            (str(position_id),),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown position_id: {position_id}")

        conviction_id = row["conviction_id"]
        if conviction_id is None:
            raise ValueError(f"Position {position_id} missing conviction_id")

        opened_at = _parse_iso(row["opened_at"]) or utc_now()
        closed_at = _parse_iso(row["closed_at"]) or utc_now()
        time_held_hours = max(0.0, (closed_at - opened_at).total_seconds() / 3600.0)

        max_drawdown_pct = float(row["max_drawdown_during"] or 0.0)
        regime_at_entry = str(row["regime_at_entry"] or "")

        # Direction correctness is determined by PnL sign (PnL already incorporates direction).
        direction_correct = float(realized_pnl) > 0.0

        # Recover domain scores at entry from conviction_log via cycle_id+symbol.
        score_row = self.db.conn.execute(
            "SELECT cycle_id, symbol FROM conviction_scores WHERE id = ?",
            (int(conviction_id),),
        ).fetchone()
        domain_scores: dict[str, float] = {}
        if score_row is not None:
            cycle_id = score_row["cycle_id"]
            symbol = score_row["symbol"]
            if cycle_id and symbol:
                cur = self.db.conn.execute(
                    "SELECT domain, domain_score FROM conviction_log WHERE cycle_id = ? AND symbol = ?",
                    (str(cycle_id), str(symbol)),
                )
                for r in cur.fetchall():
                    domain_scores[str(r["domain"])] = float(r["domain_score"]) 

        return OutcomeAttribution(
            position_id=str(position_id),
            conviction_id=int(conviction_id),
            realized_pnl=float(realized_pnl),
            direction_correct=bool(direction_correct),
            time_held_hours=float(time_held_hours),
            max_drawdown_pct=float(max_drawdown_pct),
            regime_at_entry=regime_at_entry,
            domain_scores_at_entry=domain_scores,
        )

    # ---------------------------------------------------------------------
    # 2) Domain weight adjustment
    # ---------------------------------------------------------------------

    def _current_domain_weights(self) -> dict[str, float]:
        w = self.config.weights.model_dump()
        return {k: float(v) for k, v in w.items()}

    def _preset_domain_weights(self) -> dict[str, float]:
        # Re-load preset without learned overlay.
        preset = self.config.preset
        if preset == "custom":
            # Best-effort: treat current config weights as preset if custom.
            return self._current_domain_weights()
        base = Config.from_preset(preset, repo_root=Path.cwd())
        return {k: float(v) for k, v in base.weights.model_dump().items()}

    def _window_bounds(self) -> tuple[datetime, datetime]:
        end = utc_now()
        start = end - timedelta(days=int(self.ADJUSTMENT_WINDOW_DAYS))
        return start, end

    def _closed_positions_in_window(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        rows = self.db.conn.execute(
            """
            SELECT id, asset, direction, opened_at, closed_at, realized_pnl, conviction_id
            FROM positions
            WHERE status = 'closed'
              AND closed_at IS NOT NULL
              AND closed_at >= ?
              AND closed_at <= ?
              AND conviction_id IS NOT NULL
              AND realized_pnl IS NOT NULL
            """,
            (_dt_to_iso(start), _dt_to_iso(end)),
        ).fetchall()

        out: list[dict[str, Any]] = []
        for r in rows:
            out.append({k: r[k] for k in r.keys()})
        return out

    def _cold_start_state(self, as_of: datetime) -> tuple[bool, str, float]:
        """Returns (blocked, reason, max_delta_for_this_cycle)."""

        first = self.db.conn.execute(
            "SELECT MIN(closed_at) AS first_closed FROM positions WHERE status = 'closed' AND closed_at IS NOT NULL"
        ).fetchone()
        if first is None or first["first_closed"] is None:
            return True, "cold_start_no_history", 0.0

        first_closed = _parse_iso(first["first_closed"]) or as_of
        age_days = (as_of - first_closed).days

        if age_days < 30:
            return True, "cold_start_baseline", 0.0
        if 30 <= age_days < 90:
            return False, "warm", self.MAX_WEIGHT_DELTA / 2.0
        return False, "warm", self.MAX_WEIGHT_DELTA

    def adjust_domain_weights(self) -> WeightAdjustment:
        start, end = self._window_bounds()
        positions = self._closed_positions_in_window(start, end)
        n = len(positions)

        blocked, cold_reason, max_delta = self._cold_start_state(end)
        previous = self._current_domain_weights()

        if blocked:
            return WeightAdjustment(
                previous_weights=previous,
                new_weights=previous,
                deltas={k: 0.0 for k in previous},
                observations=n,
                window_days=self.ADJUSTMENT_WINDOW_DAYS,
                applied=False,
                reason=cold_reason,
            )

        if n < self.MIN_OBSERVATIONS:
            return WeightAdjustment(
                previous_weights=previous,
                new_weights=previous,
                deltas={k: 0.0 for k in previous},
                observations=n,
                window_days=self.ADJUSTMENT_WINDOW_DAYS,
                applied=False,
                reason="insufficient_data",
            )

        # Build samples: for each position, get domain scores at entry (from conviction_log)
        # and an outcome sign (+1 win, -1 loss).
        samples: dict[str, list[tuple[float, float]]] = {k: [] for k in previous}
        for p in positions:
            conviction_id = int(p["conviction_id"])  # type: ignore[index]
            score = self.db.conn.execute(
                "SELECT cycle_id, symbol FROM conviction_scores WHERE id = ?",
                (conviction_id,),
            ).fetchone()
            if score is None:
                continue

            cycle_id = score["cycle_id"]
            symbol = score["symbol"]
            if not cycle_id or not symbol:
                continue

            o = 1.0 if float(p["realized_pnl"]) > 0.0 else -1.0
            cur = self.db.conn.execute(
                "SELECT domain, domain_score FROM conviction_log WHERE cycle_id = ? AND symbol = ?",
                (str(cycle_id), str(symbol)),
            )
            for r in cur.fetchall():
                d = str(r["domain"])
                if d not in samples:
                    continue
                try:
                    s = float(r["domain_score"])
                except Exception:
                    continue
                samples[d].append((s, o))

        # Compute correlation per domain. Domains with more consistent alignment get nudged up.
        correlations: dict[str, float] = {}
        for domain, pairs in samples.items():
            if len(pairs) < max(5, self.MIN_OBSERVATIONS // 2):
                correlations[domain] = 0.0
                continue
            xs = [p[0] for p in pairs]
            ys = [p[1] for p in pairs]
            correlations[domain] = _pearson(xs, ys)

        # Translate correlations into deltas.
        deltas: dict[str, float] = {}
        for domain, w in previous.items():
            corr = float(correlations.get(domain, 0.0))
            raw = corr * float(max_delta)
            deltas[domain] = float(_clamp(raw, -float(max_delta), float(max_delta)))

        proposed = {k: float(previous[k]) + float(deltas[k]) for k in previous}
        new_weights = _enforce_bounds_and_renormalize(
            proposed,
            min_w=self.MIN_DOMAIN_WEIGHT,
            max_w=self.MAX_DOMAIN_WEIGHT,
        )

        # Determine if we should revert due to sustained degradation.
        adjustment = WeightAdjustment(
            previous_weights=previous,
            new_weights=new_weights,
            deltas={k: float(new_weights[k] - previous[k]) for k in previous},
            observations=n,
            window_days=self.ADJUSTMENT_WINDOW_DAYS,
            applied=True,
            reason="adjusted",
        )

        if self.check_overfitting(adjustment):
            preset = self._preset_domain_weights()
            preset = _enforce_bounds_and_renormalize(
                preset,
                min_w=self.MIN_DOMAIN_WEIGHT,
                max_w=self.MAX_DOMAIN_WEIGHT,
            )
            return WeightAdjustment(
                previous_weights=previous,
                new_weights=preset,
                deltas={k: float(preset[k] - previous[k]) for k in previous},
                observations=n,
                window_days=self.ADJUSTMENT_WINDOW_DAYS,
                applied=True,
                reason="reverted",
            )

        return adjustment

    # ---------------------------------------------------------------------
    # 3) Producer scoring
    # ---------------------------------------------------------------------

    def score_producers(self) -> dict[str, ProducerScore]:
        """Compute per-producer reliability from producer_health and outcomes.

        The current repo does not yet store per-producer directional predictions in a
        first-class table, so this is a conservative initial implementation:
        - accuracy: based on proportion of closed positions with positive PnL (global),
          assigned to every producer (placeholder until signal-level attribution exists)
        - staleness_avg_ms: derived from producer_health.last_success_at vs now
        - error_rate: derived from consecutive_failures

        This still produces stable metrics and keeps the interface intact.
        """

        now = utc_now()

        # Global accuracy proxy.
        start, end = self._window_bounds()
        positions = self._closed_positions_in_window(start, end)
        if len(positions) >= self.MIN_OBSERVATIONS:
            wins = sum(1 for p in positions if float(p["realized_pnl"]) > 0.0)
            global_acc = float(wins) / float(len(positions))
        else:
            global_acc = 0.0

        rows = self.db.conn.execute("SELECT * FROM producer_health").fetchall()
        out: dict[str, ProducerScore] = {}
        for r in rows:
            name = str(r["name"])
            last_success = _parse_iso(r["last_success_at"]) if r["last_success_at"] else None
            if last_success is None:
                staleness_ms = float("inf")
            else:
                staleness_ms = float((now - last_success).total_seconds() * 1000.0)

            consecutive_failures = int(r["consecutive_failures"] or 0)
            # Simple bounded heuristic.
            error_rate = float(_clamp(consecutive_failures / 10.0, 0.0, 1.0))

            out[name] = ProducerScore(
                name=name,
                accuracy=float(global_acc),
                total_signals=int(len(positions)),
                correct_signals=int(round(global_acc * len(positions))),
                staleness_avg_ms=float(staleness_ms if math.isfinite(staleness_ms) else 1e12),
                error_rate=float(error_rate),
            )
        return out

    # ---------------------------------------------------------------------
    # 4) Corpus feedback
    # ---------------------------------------------------------------------

    def update_corpus(self) -> CorpusFeedback:
        """Update pattern/skill scores.

        Patterns: uses `pattern_matches` table rows that have `outcome` set.
        Skills: reads/writes markdown files in corpus/skills/*.
        """

        promoted: list[str] = []
        archived: list[str] = []

        # Patterns scored: count pattern_matches rows with outcome in window.
        start, end = self._window_bounds()
        rows = self.db.conn.execute(
            """
            SELECT pattern_id, outcome FROM pattern_matches
            WHERE outcome IS NOT NULL
              AND outcome_ts IS NOT NULL
              AND outcome_ts >= ? AND outcome_ts <= ?
            """,
            (_dt_to_iso(start), _dt_to_iso(end)),
        ).fetchall()

        patterns_scored = len(rows)

        # Skill scoring: scan active + pending.
        base = Path("corpus") / "skills"
        active_dir = base / "skills-active"
        pending_dir = base / "skills-pending"
        archived_dir = base / "skills-archived"
        for d in (active_dir, pending_dir, archived_dir):
            d.mkdir(parents=True, exist_ok=True)

        # Simple lifecycle: score >= +3 => promote to active, score <= -3 => archive.
        for skill_path in list(pending_dir.glob("*.md")) + list(active_dir.glob("*.md")):
            score = _read_skill_score(skill_path)
            if score >= 3 and skill_path.parent == pending_dir:
                dest = active_dir / skill_path.name
                dest.write_text(skill_path.read_text(encoding="utf-8"), encoding="utf-8")
                skill_path.unlink()
                promoted.append(dest.stem)
            if score <= -3 and skill_path.parent == active_dir:
                dest = archived_dir / skill_path.name
                dest.write_text(skill_path.read_text(encoding="utf-8"), encoding="utf-8")
                skill_path.unlink()
                archived.append(dest.stem)

        return CorpusFeedback(
            patterns_scored=int(patterns_scored),
            skills_promoted=promoted,
            skills_archived=archived,
        )

    # ---------------------------------------------------------------------
    # Overfitting checks
    # ---------------------------------------------------------------------

    def _window_avg_pnl(self) -> float:
        start, end = self._window_bounds()
        positions = self._closed_positions_in_window(start, end)
        if not positions:
            return 0.0
        return float(sum(float(p["realized_pnl"]) for p in positions) / float(len(positions)))

    def check_overfitting(self, adjustment: WeightAdjustment) -> bool:
        """Return True if we should revert."""

        # Persist a simple performance series.
        perf_path = self._data_path("learning_performance.json")
        perf: list[dict[str, Any]]
        if perf_path.exists():
            try:
                perf = json.loads(perf_path.read_text(encoding="utf-8"))
                if not isinstance(perf, list):
                    perf = []
            except Exception:
                perf = []
        else:
            perf = []

        now = utc_now().isoformat()
        avg_pnl = self._window_avg_pnl()
        perf.append({"ts": now, "avg_pnl": avg_pnl})
        perf_path.write_text(json.dumps(perf[-50:], indent=2, sort_keys=True), encoding="utf-8")

        if len(perf) < self.REVERSION_THRESHOLD + 1:
            return False

        # Degradation = avg_pnl lower than previous cycle.
        degradations = 0
        for i in range(1, self.REVERSION_THRESHOLD + 1):
            if perf[-i]["avg_pnl"] < perf[-i - 1]["avg_pnl"]:
                degradations += 1

        return degradations >= self.REVERSION_THRESHOLD

    # ---------------------------------------------------------------------
    # Orchestration
    # ---------------------------------------------------------------------

    def run(self) -> LearningResult:
        attributions: list[OutcomeAttribution] = []

        # Attribute outcomes for any closed positions that haven't been attributed yet.
        # Convention: conviction_scores.outcome is set when attributed.
        rows = self.db.conn.execute(
            """
            SELECT p.id AS position_id, p.realized_pnl AS realized_pnl
            FROM positions p
            JOIN conviction_scores cs ON cs.id = p.conviction_id
            WHERE p.status = 'closed'
              AND p.realized_pnl IS NOT NULL
              AND cs.outcome IS NULL
            ORDER BY p.closed_at ASC
            """
        ).fetchall()

        for r in rows:
            attr = self.attribute_outcome(str(r["position_id"]), float(r["realized_pnl"]))
            attributions.append(attr)
            # Write outcome back to conviction_scores.
            with self.db.conn:
                self.db.conn.execute(
                    "UPDATE conviction_scores SET outcome = ?, outcome_ts = ? WHERE id = ?",
                    (float(attr.realized_pnl), utc_now().isoformat(), int(attr.conviction_id)),
                )

        weight_adj = self.adjust_domain_weights()
        producer_scores = self.score_producers()
        corpus_fb = self.update_corpus()

        # Emit learning report event (lightweight).
        payload = {
            "attributions": len(attributions),
            "weight_adjustment": {
                "applied": weight_adj.applied,
                "reason": weight_adj.reason,
                "observations": weight_adj.observations,
                "deltas": weight_adj.deltas,
            },
            "producer_scores": {k: v.accuracy for k, v in producer_scores.items()},
            "corpus_feedback": {
                "patterns_scored": corpus_fb.patterns_scored,
                "skills_promoted": corpus_fb.skills_promoted,
                "skills_archived": corpus_fb.skills_archived,
            },
        }
        self.db.append_event(
            event_type=EventType.LEARNING_REPORT_V1,
            payload=payload,
            source="learning",
            dedupe_key=f"learning:report:{utc_now().strftime('%Y%m%d%H')}",
        )

        return LearningResult(
            outcome_attributions=attributions,
            weight_adjustment=weight_adj,
            producer_scores=producer_scores,
            corpus_feedback=corpus_fb,
            cycle_timestamp=utc_now(),
        )


def _clamp(x: float, lo: float, hi: float) -> float:
    return float(min(hi, max(lo, x)))


def _pearson(xs: list[float], ys: list[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    mx = sum(xs) / float(len(xs))
    my = sum(ys) / float(len(ys))
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    denx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    deny = math.sqrt(sum((y - my) ** 2 for y in ys))
    den = denx * deny
    if den <= 0:
        return 0.0
    return float(num / den)


def _enforce_bounds_and_renormalize(
    weights: dict[str, float],
    *,
    min_w: float,
    max_w: float,
) -> dict[str, float]:
    w = {k: float(v) for k, v in weights.items()}

    # Clamp
    for k in w:
        w[k] = float(_clamp(w[k], min_w, max_w))

    total = sum(w.values())
    if total <= 0:
        # Equal weights fallback.
        n = len(w) or 1
        return {k: 1.0 / float(n) for k in w}

    # Renormalize.
    w = {k: float(v) / float(total) for k, v in w.items()}

    # Re-clamp after normalization and renormalize again to correct drift.
    for k in w:
        w[k] = float(_clamp(w[k], min_w, max_w))
    total2 = sum(w.values())
    w = {k: float(v) / float(total2) for k, v in w.items()}

    # Final tiny drift correction.
    drift = 1.0 - sum(w.values())
    if abs(drift) > 1e-9:
        kmax = max(w.keys(), key=lambda k: w[k])
        w[kmax] = float(w[kmax]) + float(drift)

    return w


def _parse_iso(v: Any) -> datetime | None:
    if v is None:
        return None
    try:
        s = str(v)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _dt_to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def _read_skill_score(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return 0

    # Look for a YAML front-matter score: `score: <int>` in first 40 lines.
    for ln in text.splitlines()[:40]:
        if ln.strip().lower().startswith("score:"):
            try:
                return int(ln.split(":", 1)[1].strip())
            except Exception:
                return 0
    return 0


def write_learned_weights_yaml(config: Config, weights: dict[str, float]) -> None:
    """Persist learned weights overlay (surface 3)."""

    path = Path(config.data_dir) / "learned_weights.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"weights": {k: float(v) for k, v in weights.items()}}
    path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
