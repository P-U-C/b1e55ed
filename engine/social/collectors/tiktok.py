"""engine.social.collectors.tiktok

TikTok collector — STUB.

Requires Apify actor or TikTok API. Currently returns empty.
"""

from __future__ import annotations

import logging
from typing import Any

from engine.social.collectors.base import BaseCollector

logger = logging.getLogger(__name__)


class TikTokCollector(BaseCollector):
    """Stub collector for TikTok crypto content.

    Not yet implemented — returns empty list.
    Configure ``apify_api_key`` when available.
    """

    name = "tiktok"

    # Future: configurable_fields = ["apify_api_key"]

    def collect(self, symbols: list[str]) -> list[dict[str, Any]]:
        logger.debug("tiktok_collector_stub: no implementation yet, returning []")
        return []
