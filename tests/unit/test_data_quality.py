from __future__ import annotations

from datetime import UTC, datetime, timedelta

from engine.brain.data_quality import DataQualityMonitor
from engine.core.database import Database
from engine.core.events import EventType


def test_data_quality_freshness_and_staleness_detection(test_config, temp_dir):
    db = Database(temp_dir / "brain.db")
    now = datetime.now(tz=UTC)

    # Fresh technical signal
    db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "BTC", "rsi_14": 50.0},
        ts=now,
    )
    # Very stale tradfi signal
    db.append_event(
        event_type=EventType.SIGNAL_TRADFI_V1,
        payload={"symbol": "BTC", "funding_annualized": 10.0},
        ts=now - timedelta(days=5),
    )

    mon = DataQualityMonitor(test_config, db)
    res = mon.evaluate(as_of=now, domains=["technical", "tradfi"])

    assert res.per_domain_staleness_ms["technical"] is not None
    assert res.per_domain_quality["technical"] > 0.5

    assert res.per_domain_staleness_ms["tradfi"] is not None
    assert res.per_domain_quality["tradfi"] == 0.0

    adj = res.adjusted_weights({"technical": 0.5, "tradfi": 0.5})
    assert adj["technical"] == 1.0
    assert adj["tradfi"] == 0.0
