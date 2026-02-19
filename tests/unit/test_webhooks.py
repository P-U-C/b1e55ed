from __future__ import annotations

import urllib.error
from datetime import UTC, datetime

from engine.core.database import Database
from engine.core.events import EventType
from engine.core.models import Event, compute_event_hash
from engine.core.webhooks import (
    WebhookSubscription,
    add_webhook_subscription,
    dispatch_event_webhooks,
    subscription_matches,
)


def _mk_event(event_type: EventType) -> Event:
    now = datetime.now(tz=UTC)
    payload = {"x": 1}
    h = compute_event_hash(
        prev_hash=None,
        event_type=event_type,
        payload=payload,
        ts=now,
        source="test",
        trace_id=None,
        schema_version="v1",
        dedupe_key=None,
        event_id="e1",
    )
    return Event(id="e1", type=event_type, ts=now, payload=payload, source="test", hash=h)


def test_subscription_matches_globs() -> None:
    sub = WebhookSubscription(
        id=1,
        url="http://example",
        event_globs="signal.* , system.*",
        enabled=True,
        created_at="",
    )
    assert subscription_matches(sub, event_type="signal.ta.v1")
    assert subscription_matches(sub, event_type="system.kill_switch.v1")
    assert not subscription_matches(sub, event_type="brain.cycle.v1")


def test_dispatch_retries_with_backoff(monkeypatch, tmp_path) -> None:
    db = Database(tmp_path / "brain.db")
    add_webhook_subscription(db, url="http://example/hook", event_globs="signal.*")

    calls: list[float] = []
    sleeps: list[float] = []

    def fake_sleep(s: float) -> None:
        sleeps.append(float(s))

    def fake_urlopen(req, timeout: float = 0.0):  # noqa: ANN001
        calls.append(float(timeout))
        if len(calls) < 3:
            raise urllib.error.URLError("boom")

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return b"ok"

        return _Resp()

    monkeypatch.setattr("time.sleep", fake_sleep)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    dispatch_event_webhooks(db, _mk_event(EventType.SIGNAL_TA_V1))

    assert len(calls) == 3
    assert sleeps == [0.5, 1.0]


def test_dispatch_skips_nonmatching(monkeypatch, tmp_path) -> None:
    db = Database(tmp_path / "brain.db")
    add_webhook_subscription(db, url="http://example/hook", event_globs="system.*")

    def fake_urlopen(req, timeout: float = 0.0):  # noqa: ANN001
        raise AssertionError("should not be called")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    dispatch_event_webhooks(db, _mk_event(EventType.SIGNAL_TA_V1))
