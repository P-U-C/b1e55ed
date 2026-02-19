from __future__ import annotations

from datetime import UTC, datetime

from engine.core.database import Database
from engine.core.events import EventType
from engine.core.webhooks import add_webhook_subscription


def test_append_event_triggers_webhook_dispatch(temp_dir, monkeypatch) -> None:
    db = Database(temp_dir / "brain.db")

    add_webhook_subscription(db, url="http://example/hook", event_globs="signal.price_alert.*")

    sent: list[dict[str, object]] = []

    def fake_post_json(url: str, payload: dict[str, object], *, timeout_s: float) -> None:
        sent.append({"url": url, "payload": payload, "timeout_s": timeout_s})

    monkeypatch.setattr("engine.core.webhooks._post_json", fake_post_json)

    db.append_event(
        event_type=EventType.SIGNAL_PRICE_ALERT_V1,
        payload={"symbol": "BTC", "price": 123.45, "rule": "test"},
        ts=datetime.now(tz=UTC),
    )

    assert len(sent) == 1
    assert sent[0]["url"] == "http://example/hook"
    assert sent[0]["payload"]["event"]["type"] == str(EventType.SIGNAL_PRICE_ALERT_V1)
