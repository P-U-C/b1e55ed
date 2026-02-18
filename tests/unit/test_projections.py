from __future__ import annotations

from datetime import UTC, datetime

from engine.core.events import EventType
from engine.core.models import Event, compute_event_hash
from engine.core.projections import (
    OutcomesProjector,
    PositionConvictionProjector,
    PositionStateProjector,
    ProjectionManager,
    RegimeStateProjector,
    SignalsLatestProjector,
)


def _mk_event(*, eid: str, et: EventType, ts: datetime, payload: dict, prev_hash: str | None = None) -> Event:
    h = compute_event_hash(prev_hash=prev_hash, event_type=et, payload=payload)
    return Event(id=eid, type=et, ts=ts, payload=payload, prev_hash=prev_hash, hash=h)


def test_signals_latest_projector_latest_per_symbol_and_type() -> None:
    p = SignalsLatestProjector()
    e1 = _mk_event(
        eid="1",
        et=EventType.SIGNAL_TA_V1,
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        payload={"symbol": "BTC", "rsi_14": 40.0},
    )
    e2 = _mk_event(
        eid="2",
        et=EventType.SIGNAL_TA_V1,
        ts=datetime(2026, 1, 2, tzinfo=UTC),
        payload={"symbol": "BTC", "rsi_14": 60.0},
        prev_hash=e1.hash,
    )
    p.handle(e1)
    p.handle(e2)

    state = p.get_state()
    assert state["BTC"][str(EventType.SIGNAL_TA_V1)]["payload"]["rsi_14"] == 60.0


def test_regime_state_projector_tracks_current() -> None:
    p = RegimeStateProjector()
    e = _mk_event(
        eid="1",
        et=EventType.REGIME_CHANGE_V1,
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        payload={"regime": "risk_off"},
    )
    p.handle(e)
    s = p.get_state()
    assert s["current"]["regime"] == "risk_off"
    assert len(s["history"]) == 1


def test_position_state_projector_lifecycle() -> None:
    p = PositionStateProjector()
    opened = _mk_event(
        eid="1",
        et=EventType.POSITION_OPENED_V1,
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        payload={"position_id": "p1", "symbol": "ETH", "status": "open"},
    )
    closed = _mk_event(
        eid="2",
        et=EventType.POSITION_CLOSED_V1,
        ts=datetime(2026, 1, 2, tzinfo=UTC),
        payload={"position_id": "p1", "symbol": "ETH", "status": "closed"},
        prev_hash=opened.hash,
    )
    p.handle(opened)
    p.handle(closed)

    s = p.get_state()["positions"]["p1"]
    assert s["status"] == "closed"
    assert s["closed_at"] == datetime(2026, 1, 2, tzinfo=UTC)


def test_position_conviction_projector_latest_and_link_by_position() -> None:
    p = PositionConvictionProjector()
    e = _mk_event(
        eid="1",
        et=EventType.CONVICTION_V1,
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        payload={
            "symbol": "SOL",
            "direction": "long",
            "magnitude": 7.0,
            "regime": "neutral",
            "commitment_hash": "abc",
            "position_id": "pos-1",
        },
    )
    p.handle(e)
    s = p.get_state()
    assert s["latest_by_symbol"]["SOL"]["commitment_hash"] == "abc"
    assert s["by_position"]["pos-1"]["symbol"] == "SOL"


def test_outcomes_projector_records_close_outcome() -> None:
    p = OutcomesProjector()
    e = _mk_event(
        eid="1",
        et=EventType.POSITION_CLOSED_V1,
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        payload={
            "position_id": "p1",
            "symbol": "BTC",
            "realized_pnl": 123.0,
            "exit_reason": "tp",
        },
    )
    p.handle(e)
    s = p.get_state()["outcomes"]["p1"]
    assert s["realized_pnl"] == 123.0


def test_projection_manager_rebuild_from_replay() -> None:
    pm = ProjectionManager()
    e1 = _mk_event(
        eid="1",
        et=EventType.SIGNAL_TA_V1,
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        payload={"symbol": "BTC", "rsi_14": 10.0},
    )
    e2 = _mk_event(
        eid="2",
        et=EventType.SIGNAL_TA_V1,
        ts=datetime(2026, 1, 2, tzinfo=UTC),
        payload={"symbol": "BTC", "rsi_14": 20.0},
        prev_hash=e1.hash,
    )
    pm.rebuild([e1, e2])
    st = pm.get_state()
    assert st["signals_latest"]["BTC"][str(EventType.SIGNAL_TA_V1)]["payload"]["rsi_14"] == 20.0
