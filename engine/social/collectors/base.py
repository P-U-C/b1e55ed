"""engine.social.collectors.base

Base class for social data collectors.

Every collector speaks the same language: give me symbols, I give you dicts.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseCollector(ABC):
    """Base class for social data collectors."""

    name: str = "unknown"

    @abstractmethod
    def collect(self, symbols: list[str]) -> list[dict[str, Any]]:
        """Collect social data for given symbols.

        Returns list of dicts with at minimum:
        - symbol: str
        - sentiment: float (-1.0 to 1.0)
        - source: str (collector name)
        - volume: int (mention count or similar)
        """
        ...
