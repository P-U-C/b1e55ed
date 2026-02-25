"""engine.brain.hooks

Pre/post cycle hooks.

The orchestrator is a coordinator. Hooks are where integration lives.

"The conductor does not play the instruments." (see orchestrator)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.core.config import Config
from engine.core.database import Database


@dataclass
class PreCycleContext:
    config: Config
    db: Database
    cycle_id: str


@dataclass
class PostCycleContext:
    config: Config
    db: Database
    cycle_id: str
    result: Any


class BrainHooks:
    def __init__(self, config: Config, db: Database):
        self.config = config
        self.db = db

    def pre_cycle(self, ctx: PreCycleContext) -> None:
        # Placeholder for: load positions, check kill switch, etc.
        return None

    def post_cycle(self, ctx: PostCycleContext) -> None:
        try:
            from engine.integration.learning_loop import LearningLoopIntegration

            integration = LearningLoopIntegration(db=self.db, config=self.config)
            if integration.should_run("daily"):
                integration.run_daily()
        except Exception:
            import logging

            logging.getLogger("b1e55ed.hooks").warning("Learning loop failed in post_cycle", exc_info=True)
