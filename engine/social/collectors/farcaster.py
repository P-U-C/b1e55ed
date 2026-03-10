"""engine.social.collectors.farcaster

Farcaster collector — STUB.

Requires Neynar API key or Farcaster hub access. Currently returns empty.
"""

from __future__ import annotations

import logging
from typing import Any

from engine.social.collectors.base import BaseCollector

logger = logging.getLogger(__name__)


class FarcasterCollector(BaseCollector):
    """Stub collector for Farcaster social data.

    Not yet implemented — returns empty list.
    Configure ``neynar_api_key`` when available.
    """

    name = "farcaster"

    # Future: configurable_fields = ["neynar_api_key"]

    def collect(self, symbols: list[str]) -> list[dict[str, Any]]:
        logger.debug("farcaster_collector_stub: no implementation yet, returning []")
        return []
