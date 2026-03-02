from __future__ import annotations

from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    UTC = UTC  # noqa: N806


from engine.brain.orchestrator import BrainOrchestrator
from engine.core.database import Database
from engine.core.events import EventType
from engine.security.identity import generate_node_identity


def _seed_signals(db: Database, *, now: datetime) -> None:
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


def _run_cycle_and_get_marker_payload(test_config, temp_dir, monkeypatch) -> tuple[dict, str]:
    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "test")
    ident = generate_node_identity()
    db = Database(temp_dir / "brain.db")

    now = datetime.now(tz=UTC)
    _seed_signals(db, now=now)

    orch = BrainOrchestrator(test_config, db, ident)
    result = orch.run_cycle(["BTC"])

    cycle_events = db.get_events(event_type=EventType.BRAIN_CYCLE_V1, limit=10)
    marker = next((e for e in cycle_events if e.payload.get("cycle_id") == result.cycle_id), None)
    assert marker is not None

    return marker.payload, result.cycle_id


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


def test_brain_cycle_v1_payload_has_domain_scores(test_config, temp_dir, monkeypatch):
    payload, _ = _run_cycle_and_get_marker_payload(test_config, temp_dir, monkeypatch)

    assert "domain_scores" in payload
    assert isinstance(payload["domain_scores"], dict)
    assert "BTC" in payload["domain_scores"]
    assert isinstance(payload["domain_scores"]["BTC"], dict)


def test_brain_cycle_v1_payload_has_regime(test_config, temp_dir, monkeypatch):
    payload, _ = _run_cycle_and_get_marker_payload(test_config, temp_dir, monkeypatch)

    assert "regime" in payload
    assert isinstance(payload["regime"], dict)
    assert payload["regime"].get("BTC", "unknown") in {"BULL", "BEAR", "CRISIS", "TRANSITION", "unknown"}


def test_brain_cycle_v1_payload_has_conviction(test_config, temp_dir, monkeypatch):
    payload, _ = _run_cycle_and_get_marker_payload(test_config, temp_dir, monkeypatch)

    assert "conviction" in payload
    assert isinstance(payload["conviction"], dict)
    assert "BTC" in payload["conviction"]

    btc_conviction = payload["conviction"]["BTC"]
    assert {"pcs", "magnitude", "direction", "capped_by_regime", "pre_cap_magnitude"}.issubset(btc_conviction.keys())


def test_brain_cycle_v1_payload_has_cycle_duration_ms(test_config, temp_dir, monkeypatch):
    payload, _ = _run_cycle_and_get_marker_payload(test_config, temp_dir, monkeypatch)

    assert "cycle_duration_ms" in payload
    assert isinstance(payload["cycle_duration_ms"], int)
    assert payload["cycle_duration_ms"] >= 0
