from __future__ import annotations

from datetime import UTC, datetime

from engine.brain.orchestrator import BrainOrchestrator
from engine.core.database import Database
from engine.core.events import EventType
from engine.security.identity import generate_node_identity


def test_orchestrator_full_cycle_mock(test_config, temp_dir, monkeypatch):
    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "test")
    ident = generate_node_identity()

    db = Database(temp_dir / "brain.db")

    now = datetime.now(tz=UTC)
    # Minimal signals for one symbol
    db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "BTC", "rsi_14": 35.0, "trend_strength": 0.7},
        ts=now,
    )
    db.append_event(
        event_type=EventType.SIGNAL_TRADFI_V1,
        payload={"symbol": "BTC", "funding_annualized": 10.0, "basis_annualized": 5.0},
        ts=now,
    )

    orch = BrainOrchestrator(test_config, db, ident)
    res = orch.run_cycle(["BTC"])

    assert res.cycle_id
    assert "BTC" in res.synthesis
    assert "BTC" in res.convictions

    # Conviction event emitted
    evs = db.get_events(event_type=EventType.CONVICTION_V1, limit=10)
    assert len(evs) >= 1
