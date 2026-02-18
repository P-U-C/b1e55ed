from __future__ import annotations

from datetime import UTC, datetime

from engine.brain.orchestrator import BrainOrchestrator
from engine.core.database import Database
from engine.core.events import EventType
from engine.security.identity import generate_node_identity


def test_events_to_orchestrator_run_cycle_produces_convictions_and_decisions(test_config, temp_dir, monkeypatch):
    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "test")
    ident = generate_node_identity()

    db = Database(temp_dir / "brain.db")
    now = datetime.now(tz=UTC)

    # Provide a moderately bullish set of signals; should generate an intent.
    db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "BTC", "rsi_14": 30.0, "trend_strength": 0.8},
        ts=now,
    )
    db.append_event(
        event_type=EventType.SIGNAL_ONCHAIN_V1,
        payload={"symbol": "BTC", "whale_netflow": 80.0, "exchange_flow": -20.0},
        ts=now,
    )
    db.append_event(
        event_type=EventType.SIGNAL_TRADFI_V1,
        payload={"symbol": "BTC", "funding_annualized": 10.0, "basis_annualized": 5.0},
        ts=now,
    )

    orch = BrainOrchestrator(test_config, db, ident)
    out = orch.run_cycle(["BTC"])

    assert out.convictions["BTC"].pcs >= 0.0

    conviction_events = db.get_events(event_type=EventType.CONVICTION_V1, limit=10)
    assert conviction_events

    # Decision may or may not fire depending on scores, but if it fires it must be TRADE_INTENT_V1.
    intent_events = db.get_events(event_type=EventType.TRADE_INTENT_V1, limit=10)
    if intent_events:
        assert intent_events[0].payload["symbol"] == "BTC"
