"""Post Fiat Signals adapter producer.

Ingests directional signals from a Post Fiat signals endpoint via the
external adapter framework and emits SIGNAL_TRADFI_V1 events.
"""

from __future__ import annotations

from engine.external.base import BaseExternalProducer
from engine.external.models import ExternalObservation, RawExternalRecord
from engine.producers.registry import register

_ACTION_MAP: dict[str, str] = {
    "BUY": "bullish",
    "SELL": "bearish",
    "HOLD": "neutral",
}

_HORIZON_HOURS = 168  # Post Fiat uses a weekly evaluation horizon.


@register("post-fiat-signals", domain="tradfi")
class PostFiatSignalsProducer(BaseExternalProducer):
    """Producer that ingests Post Fiat directional signals."""

    name = "post-fiat-signals"
    domain = "tradfi"
    schedule = "* * * * *"  # poll every minute; controlled by poll_interval_sec in spec

    SPEC_PATH = "engine/external/specs/post_fiat_signals.yaml"

    def normalize(self, raw: RawExternalRecord) -> list[ExternalObservation]:  # type: ignore[override]
        """Parse post-fiat-signals response into ExternalObservations.

        Expected payload structure::

            {
                "signals": [
                    {
                        "ticker": "BTC",
                        "action": "BUY",
                        "confidence": 0.82,
                        "timestamp": "2025-01-01T00:00:00Z",
                        "regime": "bull",
                        "signal_type": "momentum",
                        "hit_rate": 0.67,
                        "avg_return": 0.12,
                        "is_stale": false
                    },
                    ...
                ],
                "health": {"status": "HEALTHY"}
            }
        """
        signals = raw.raw_payload.get("signals", [])
        health_status = raw.raw_payload.get("health", {}).get("status", "HEALTHY")

        observations: list[ExternalObservation] = []
        for s in signals:
            action = str(s.get("action", "")).upper()
            direction = _ACTION_MAP.get(action, "neutral")

            raw_conf = s.get("confidence", 0.5)
            try:
                confidence = float(raw_conf)
            except (TypeError, ValueError):
                confidence = 0.5

            hit_rate = s.get("hit_rate")
            avg_return = s.get("avg_return")

            observations.append(
                ExternalObservation(
                    symbol=s.get("ticker", ""),
                    direction=direction,
                    confidence=confidence,
                    horizon_hours=_HORIZON_HOURS,
                    observed_at=s.get("timestamp", ""),
                    regime=s.get("regime"),
                    signal_type=s.get("signal_type"),
                    source_assertion=action or None,
                    hit_rate=float(hit_rate) if hit_rate is not None else None,
                    avg_return=float(avg_return) if avg_return is not None else None,
                    is_stale=bool(s.get("is_stale", False)),
                    health_state=health_status,
                    raw=s,
                )
            )

        return observations
