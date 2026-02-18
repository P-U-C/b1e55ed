"""engine.integration.learning_loop

Integration glue for the compound learning system.

- Called by orchestrator post-cycle hooks (when wired)
- Schedules learning runs by cadence:
  - daily: attribution (outcomes)
  - weekly: weight adjustment proposal
  - monthly: full learning cycle
- Persists learned weights to:
  - DB (`learning_weights` table)
  - YAML overlay (`data/learned_weights.yaml`) which Config loads on startup

This module is intentionally conservative: it does not require a running
scheduler to be useful. The orchestrator (or operator) can call `run_*()`.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import yaml

from engine.brain.learning import LearningLoop, write_learned_weights_yaml
from engine.core.config import Config
from engine.core.database import Database
from engine.core.time import utc_now

CycleType = Literal["daily", "weekly", "monthly"]


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


class LearningLoopIntegration:
    def __init__(self, *, db: Database, config: Config):
        self.db = db
        self.config = config
        self.loop = LearningLoop(db=db, config=config)

    def _last_run_ts(self, cycle_type: CycleType) -> datetime | None:
        row = self.db.conn.execute(
            "SELECT ts FROM learning_weights WHERE cycle_type = ? ORDER BY ts DESC LIMIT 1",
            (str(cycle_type),),
        ).fetchone()
        if row is None:
            return None
        try:
            return datetime.fromisoformat(str(row["ts"]).replace("Z", "+00:00")).astimezone(UTC)
        except Exception:
            return None

    def should_run(self, cycle_type: CycleType, *, now: datetime | None = None) -> bool:
        ref = now or utc_now()
        last = self._last_run_ts(cycle_type)
        if last is None:
            return True

        if cycle_type == "daily":
            return (ref - last) >= timedelta(hours=24)
        if cycle_type == "weekly":
            return (ref - last) >= timedelta(days=7)
        if cycle_type == "monthly":
            return (ref - last) >= timedelta(days=30)
        return False

    def run_monthly(self) -> dict[str, Any]:
        result = self.loop.run()

        wa = result.weight_adjustment
        # Persist domain weight changes to DB history.
        if wa.applied and wa.new_weights != wa.previous_weights:
            with self.db.conn:
                for domain, old_w in wa.previous_weights.items():
                    new_w = float(wa.new_weights.get(domain, old_w))
                    delta = float(new_w - float(old_w))
                    self.db.conn.execute(
                        """
                        INSERT INTO learning_weights (cycle_type, domain, old_weight, new_weight, delta, reason, ts)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "monthly",
                            str(domain),
                            float(old_w),
                            float(new_w),
                            float(delta),
                            str(wa.reason),
                            _iso(result.cycle_timestamp),
                        ),
                    )

            # Persist overlay YAML.
            write_learned_weights_yaml(self.config, wa.new_weights)

        return {
            "cycle_type": "monthly",
            "timestamp": result.cycle_timestamp,
            "weight_adjustment": asdict(wa),
            "outcome_attributions": [asdict(a) for a in result.outcome_attributions],
        }

    def run_weekly(self) -> dict[str, Any]:
        # Weekly: only propose/compute weight adjustment.
        wa = self.loop.adjust_domain_weights()
        if wa.applied and wa.new_weights != wa.previous_weights:
            with self.db.conn:
                for domain, old_w in wa.previous_weights.items():
                    new_w = float(wa.new_weights.get(domain, old_w))
                    delta = float(new_w - float(old_w))
                    self.db.conn.execute(
                        """
                        INSERT INTO learning_weights (cycle_type, domain, old_weight, new_weight, delta, reason, ts)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "weekly",
                            str(domain),
                            float(old_w),
                            float(new_w),
                            float(delta),
                            str(wa.reason),
                            _iso(utc_now()),
                        ),
                    )
        return {"cycle_type": "weekly", "weight_adjustment": asdict(wa)}

    def run_daily(self) -> dict[str, Any]:
        # Daily: attribution only (writes outcomes back to conviction_scores).
        res = self.loop.run()
        return {
            "cycle_type": "daily",
            "timestamp": res.cycle_timestamp,
            "attributions": [asdict(a) for a in res.outcome_attributions],
        }
