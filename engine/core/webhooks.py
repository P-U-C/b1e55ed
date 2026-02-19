"""engine.core.webhooks

Persistent outbound webhook subscriptions + dispatcher.

Design goals:
- stdlib-only HTTP (urllib.request)
- best-effort delivery (never block/abort event persistence)
- simple glob matching on event type strings (fnmatch)
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any

from engine.core.models import Event


@dataclass(frozen=True)
class WebhookSubscription:
    id: int
    url: str
    event_globs: str
    enabled: bool
    created_at: str


def _split_event_globs(event_globs: str) -> list[str]:
    # Stored as a comma-separated list.
    parts = [p.strip() for p in event_globs.split(",")]
    return [p for p in parts if p]


def subscription_matches(sub: WebhookSubscription, *, event_type: str) -> bool:
    return any(fnmatchcase(event_type, g) for g in _split_event_globs(sub.event_globs))


def list_webhook_subscriptions(db: Any) -> list[WebhookSubscription]:
    rows = db.conn.execute("SELECT id, url, event_globs, enabled, created_at FROM webhook_subscriptions ORDER BY id ASC").fetchall()
    out: list[WebhookSubscription] = []
    for r in rows:
        out.append(
            WebhookSubscription(
                id=int(r[0]),
                url=str(r[1]),
                event_globs=str(r[2]),
                enabled=bool(int(r[3])),
                created_at=str(r[4]),
            )
        )
    return out


def add_webhook_subscription(db: Any, *, url: str, event_globs: str, enabled: bool = True) -> int:
    with db.conn:
        cur = db.conn.execute(
            "INSERT INTO webhook_subscriptions (url, event_globs, enabled) VALUES (?, ?, ?)",
            (url, event_globs, 1 if enabled else 0),
        )
    return int(cur.lastrowid)


def remove_webhook_subscription(db: Any, *, sub_id: int) -> bool:
    with db.conn:
        cur = db.conn.execute("DELETE FROM webhook_subscriptions WHERE id = ?", (int(sub_id),))
    return int(cur.rowcount) > 0


def _post_json(url: str, payload: dict[str, Any], *, timeout_s: float) -> None:
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "b1e55ed-webhooks/1"},
    )
    # urlopen timeout covers connect + read.
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
        _ = resp.read()  # drain


def dispatch_event_webhooks(db: Any, event: Event) -> None:
    """Dispatch webhooks for a committed event.

    Best-effort semantics:
    - does nothing if no enabled subscriptions match
    - for each subscription, tries up to 3 times with exponential backoff
    """

    event_type = str(event.type)

    rows = db.conn.execute("SELECT id, url, event_globs, enabled, created_at FROM webhook_subscriptions WHERE enabled = 1").fetchall()

    if not rows:
        return

    payload = {
        "event": {
            "id": event.id,
            "type": event_type,
            "ts": event.ts.isoformat(),
            "observed_at": event.observed_at.isoformat() if event.observed_at else None,
            "source": event.source,
            "trace_id": event.trace_id,
            "schema_version": event.schema_version,
            "dedupe_key": event.dedupe_key,
            "payload": event.payload,
            "prev_hash": event.prev_hash,
            "hash": event.hash,
        }
    }

    for r in rows:
        sub = WebhookSubscription(
            id=int(r[0]),
            url=str(r[1]),
            event_globs=str(r[2]),
            enabled=bool(int(r[3])),
            created_at=str(r[4]),
        )
        if not subscription_matches(sub, event_type=event_type):
            continue

        backoff_s = 0.5
        for attempt in range(1, 4):
            try:
                _post_json(sub.url, payload, timeout_s=3.0)
                break
            except (urllib.error.URLError, TimeoutError, ValueError):
                if attempt < 3:
                    time.sleep(backoff_s)
                    backoff_s *= 2
