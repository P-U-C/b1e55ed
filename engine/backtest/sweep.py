"""engine.backtest.sweep

Parameter sweep harness.

B1a includes only the contract. B1b will implement real strategy grids.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SweepResult:
    items: list[dict[str, Any]]
