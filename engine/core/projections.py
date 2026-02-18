"""engine.core.projections

Materialized views from event replay.

Projections are derived state. The event log is the source of truth.
If projections are corrupted, they can be rebuilt from event replay.

The map is not the territory, but a good projection comes close.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from engine.core.events import EventType
from engine.core.models import Event


class Projector:
    def handle(self, event: Event) -> None: ...

    def get_state(self) -> dict[str, Any]: ...


@dataclass
class OutcomesProjector(Projector):
    """Tracks trade outcomes (closed positions)."""

    outcomes: dict[str, dict[str, Any]] = field(default_factory=dict)

    def handle(self, event: Event) -> None:
        if event.type != EventType.POSITION_CLOSED_V1 and "realized_pnl" not in event.payload:
            return

        pid = str(event.payload.get("position_id") or "")
        symbol = str(event.payload.get("symbol") or event.payload.get("asset") or "").upper()
        if not pid or not symbol:
            return

        self.outcomes[pid] = {
            "position_id": pid,
            "symbol": symbol,
            "realized_pnl": event.payload.get("realized_pnl"),
            "realized_pnl_pct": event.payload.get("realized_pnl_pct"),
            "exit_reason": event.payload.get("exit_reason"),
            "event_id": event.id,
            "ts": event.ts,
        }

    def get_state(self) -> dict[str, Any]:
        return {"outcomes": dict(self.outcomes)}


@dataclass
class PositionConvictionProjector(Projector):
    """Links positions to conviction scores."""

    latest_by_symbol: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_position: dict[str, dict[str, Any]] = field(default_factory=dict)

    def handle(self, event: Event) -> None:
        if event.type != EventType.CONVICTION_V1 and "commitment_hash" not in event.payload:
            return

        symbol = str(event.payload.get("symbol") or "").upper()
        if not symbol:
            return

        row = {
            "symbol": symbol,
            "commitment_hash": event.payload.get("commitment_hash"),
            "magnitude": event.payload.get("magnitude"),
            "direction": event.payload.get("direction"),
            "regime": event.payload.get("regime"),
            "event_id": event.id,
            "ts": event.ts,
        }
        self.latest_by_symbol[symbol] = row

        pid = event.payload.get("position_id")
        if pid is not None:
            self.by_position[str(pid)] = row

    def get_state(self) -> dict[str, Any]:
        return {
            "latest_by_symbol": dict(self.latest_by_symbol),
            "by_position": dict(self.by_position),
        }


@dataclass
class PositionStateProjector(Projector):
    """Position lifecycle (open → monitoring → closing → closed)."""

    positions: dict[str, dict[str, Any]] = field(default_factory=dict)

    def handle(self, event: Event) -> None:
        if event.type not in {EventType.POSITION_OPENED_V1, EventType.POSITION_UPDATED_V1, EventType.POSITION_CLOSED_V1}:
            if "position_id" not in event.payload:
                return

        pid = str(event.payload.get("position_id") or "")
        if not pid:
            return

        symbol = str(event.payload.get("symbol") or event.payload.get("asset") or "").upper() or None
        status = str(event.payload.get("status") or "")
        if not status:
            status = {
                EventType.POSITION_OPENED_V1: "open",
                EventType.POSITION_UPDATED_V1: "monitoring",
                EventType.POSITION_CLOSED_V1: "closed",
            }.get(event.type, "unknown")

        prev = self.positions.get(pid) or {}

        opened_at = prev.get("opened_at")
        if opened_at is None and event.type == EventType.POSITION_OPENED_V1:
            opened_at = event.ts

        closed_at = prev.get("closed_at")
        if event.type == EventType.POSITION_CLOSED_V1:
            closed_at = event.ts

        self.positions[pid] = {
            "position_id": pid,
            "symbol": symbol or prev.get("symbol"),
            "status": status,
            "opened_at": opened_at,
            "closed_at": closed_at,
            "last_event_id": event.id,
            "last_ts": event.ts,
        }

    def get_state(self) -> dict[str, Any]:
        return {"positions": dict(self.positions)}


@dataclass
class RegimeStateProjector(Projector):
    """Current market regime."""

    current: dict[str, Any] | None = None
    history: list[dict[str, Any]] = field(default_factory=list)

    def handle(self, event: Event) -> None:
        if event.type != EventType.REGIME_CHANGE_V1 and "regime" not in event.payload:
            return

        regime = str(event.payload.get("regime") or "").strip() or "TRANSITION"
        row = {"regime": regime, "ts": event.ts, "event_id": event.id}
        self.current = row
        self.history.append(row)

    def get_state(self) -> dict[str, Any]:
        return {"current": self.current, "history": list(self.history)}


@dataclass
class SignalsLatestProjector(Projector):
    """Latest signal per type per symbol."""

    _latest: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)

    def handle(self, event: Event) -> None:
        if not str(event.type).startswith("signal."):
            return

        symbol = str(event.payload.get("symbol") or "").upper()
        if not symbol:
            return

        signal_type = str(event.payload.get("signal_type") or str(event.type))
        key = (symbol, signal_type)

        prev = self._latest.get(key)
        if prev is not None:
            prev_ts: datetime | None = prev.get("ts")
            if isinstance(prev_ts, datetime) and event.ts < prev_ts:
                return

        self._latest[key] = {
            "symbol": symbol,
            "signal_type": signal_type,
            "event_type": str(event.type),
            "event_id": event.id,
            "ts": event.ts,
            "payload": dict(event.payload),
        }

    def get_state(self) -> dict[str, Any]:
        out: dict[str, dict[str, Any]] = {}
        for (symbol, signal_type), row in self._latest.items():
            out.setdefault(symbol, {})[signal_type] = {
                "event_id": row["event_id"],
                "ts": row["ts"],
                "payload": row["payload"],
            }
        return out


class ProjectionManager:
    """Orchestrates projectors and supports rebuild from event replay."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.projectors: list[Projector] = [
            SignalsLatestProjector(),
            RegimeStateProjector(),
            PositionConvictionProjector(),
            PositionStateProjector(),
            OutcomesProjector(),
        ]

    def handle(self, event: Event) -> None:
        with self._lock:
            for p in self.projectors:
                p.handle(event)

    def rebuild(self, events: Iterable[Event]) -> None:
        with self._lock:
            self.__init__()
            for ev in events:
                self.handle(ev)

    def get_state(self) -> dict[str, Any]:
        return {
            "signals_latest": self.projectors[0].get_state(),
            "regime_state": self.projectors[1].get_state(),
            "position_conviction": self.projectors[2].get_state(),
            "position_state": self.projectors[3].get_state(),
            "outcomes": self.projectors[4].get_state(),
        }
