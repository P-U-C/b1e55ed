"""engine.social.collectors.telegram

Telegram collector — STUB.

Requires Telegram Bot API token and channel access. Currently returns empty.
"""

from __future__ import annotations

import logging
from typing import Any

from engine.social.collectors.base import BaseCollector

logger = logging.getLogger(__name__)


class TelegramCollector(BaseCollector):
    """Stub collector for Telegram channel data.

    Not yet implemented — returns empty list.
    Configure ``telegram_bot_token`` and ``telegram_channels`` when available.
    """

    name = "telegram"

    # Future: configurable_fields = ["telegram_bot_token", "telegram_channels"]

    def collect(self, symbols: list[str]) -> list[dict[str, Any]]:
        logger.debug("telegram_collector_stub: no implementation yet, returning []")
        return []
