"""engine.producers.template

Copy-this producer.

This is the "add a new producer in five minutes" experience.

TODO (new contributor):
- rename TemplateProducer
- pick a real domain
- replace the dummy payload with your real observation
- add a second event if the world is complicated (it is)

Precision is the tone. Not hype.
"""

from __future__ import annotations

from datetime import UTC, datetime

from engine.core.events import EventType
from engine.core.models import Event
from engine.producers.base import BaseProducer
from engine.producers.registry import register


@register("template", domain="events")
class TemplateProducer(BaseProducer):
    """A small, working example used by unit tests."""

    schedule = "continuous"

    def collect(self) -> list[dict]:
        now = datetime.now(tz=UTC)
        return [{"ts": now.isoformat()}]

    def normalize(self, raw: list[dict]) -> list[Event]:
        ts = datetime.fromisoformat(raw[0]["ts"]).astimezone(UTC)
        payload = {
            "symbol": "BTC",
            "headline_sentiment": None,
            "impact_score": None,
            "event_count": 0,
            "catalysts": ["template"],
        }
        return [
            self.draft_event(
                event_type=EventType.SIGNAL_EVENTS_V1,
                payload=payload,
                ts=ts,
                source=self.name,
            )
        ]
