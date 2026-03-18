"""engine.social.collectors.trends

Google Trends collector — STUB.

Requires Google Trends API or pytrends. Currently returns empty.
Kept as a placeholder for future implementation.
"""

from __future__ import annotations

import logging
from typing import Any

from engine.social.collectors.base import BaseCollector

logger = logging.getLogger(__name__)


class TrendsCollector(BaseCollector):
    """Stub collector for Google Trends data.

    Not yet implemented — returns empty list.
    Configure ``google_trends_api_key`` when available.
    """

    name = "trends"

    # Future: configurable_fields = ["google_trends_api_key"]

    def collect(self, symbols: list[str]) -> list[dict[str, Any]]:
        logger.debug("trends_collector_stub: no implementation yet, returning []")
        return []
