"""Best-effort Telegram alerts for kill-switch state changes."""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

_LOG = logging.getLogger("b1e55ed.kill_switch_alerts")


def _utc_timestamp() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _send_sync(*, token: str, chat_id: str, text: str) -> None:
    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(req, timeout=4) as resp:
        raw = resp.read()

    if not raw:
        return

    payload = json.loads(raw.decode("utf-8"))
    if isinstance(payload, dict) and payload.get("ok") is False:
        raise RuntimeError(str(payload.get("description") or "telegram sendMessage returned ok=false"))


def send_telegram_kill_switch_message(text: str) -> None:
    """Dispatch Telegram message asynchronously; never raises."""

    token = str(os.getenv("TELEGRAM_BOT_TOKEN", "") or "").strip()
    chat_id = str(os.getenv("TELEGRAM_CHAT_ID", "") or "").strip()
    if not token or not chat_id:
        return

    def _worker() -> None:
        try:
            _send_sync(token=token, chat_id=chat_id, text=text)
        except Exception:
            _LOG.warning("Kill-switch Telegram notification failed", exc_info=True)

    try:
        threading.Thread(target=_worker, name="kill-switch-telegram-alert", daemon=True).start()
    except Exception:
        _LOG.warning("Failed to start kill-switch Telegram alert thread", exc_info=True)


def notify_kill_switch_escalated(*, previous_level: int, level: int, level_name: str, reason: str) -> None:
    message = f"🚨 Kill Switch Escalated\nLevel: {previous_level} → {level} ({level_name})\nReason: {reason or 'unspecified'}\nTime: {_utc_timestamp()}"
    send_telegram_kill_switch_message(message)


def notify_kill_switch_reset(*, previous_level: int, level: int, actor: str) -> None:
    message = f"✅ Kill Switch Reset\nLevel: {previous_level} → {level}\nBy: {actor or 'unknown'}\nTime: {_utc_timestamp()}"
    send_telegram_kill_switch_message(message)
