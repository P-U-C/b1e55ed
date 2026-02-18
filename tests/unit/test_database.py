from __future__ import annotations

from pathlib import Path

import pytest

from engine.core.database import Database
from engine.core.events import EventType
from engine.core.exceptions import DedupeConflictError


def test_append_and_query_round_trip(temp_dir: Path) -> None:
    db = Database(temp_dir / "brain.db")
    try:
        e = db.append_event(
            event_type=EventType.SIGNAL_TA_V1, payload={"symbol": "BTC", "rsi_14": 55.0}
        )
        got = db.get_events(event_type=EventType.SIGNAL_TA_V1, limit=10)
        assert got[0].id == e.id
        assert got[0].payload["symbol"] == "BTC"
    finally:
        db.close()


def test_hash_chain_survives_like_bitcoin_genesis(temp_dir: Path) -> None:
    db = Database(temp_dir / "brain.db")
    try:
        db.append_event(event_type=EventType.SIGNAL_TA_V1, payload={"symbol": "BTC"})
        db.append_event(event_type=EventType.SIGNAL_TA_V1, payload={"symbol": "ETH"})
        assert db.verify_hash_chain() is True
    finally:
        db.close()


def test_dedup_is_idempotent_and_conflicts_on_payload_change(temp_dir: Path) -> None:
    db = Database(temp_dir / "brain.db")
    try:
        k = "signal.ta.v1:BTC:20260217"
        e1 = db.append_event(
            event_type=EventType.SIGNAL_TA_V1, payload={"symbol": "BTC"}, dedupe_key=k
        )
        e2 = db.append_event(
            event_type=EventType.SIGNAL_TA_V1, payload={"symbol": "BTC"}, dedupe_key=k
        )
        assert e1.id == e2.id

        with pytest.raises(DedupeConflictError):
            db.append_event(
                event_type=EventType.SIGNAL_TA_V1,
                payload={"symbol": "BTC", "rsi_14": 1.0},
                dedupe_key=k,
            )
    finally:
        db.close()


def test_batch_append(temp_dir: Path) -> None:
    db = Database(temp_dir / "brain.db")
    try:
        out = db.append_events_batch(
            [
                (EventType.SIGNAL_TA_V1, {"symbol": "BTC"}, "k1"),
                (EventType.SIGNAL_TA_V1, {"symbol": "ETH"}, "k2"),
            ],
            source="unit",
        )
        assert len(out) == 2
        assert out[0].source == "unit"
    finally:
        db.close()
