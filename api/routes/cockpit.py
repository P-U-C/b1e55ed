"""Cockpit state endpoint — single-screen trading decision view."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017
from typing import Any

from fastapi import APIRouter, Depends

from api.deps import get_db
from engine.core.database import Database

router = APIRouter()

_KS_LEVEL_NAMES = {0: "SAFE", 1: "CAUTION", 2: "DEFENSIVE", 3: "LOCKDOWN", 4: "EMERGENCY", 5: "SHUTDOWN"}


def _get_top_call(db: Database) -> dict[str, Any] | None:
    row = db.execute(
        "SELECT symbol, direction, confidence, magnitude, timeframe, pcs_score, cts_score, ts FROM conviction_scores ORDER BY ts DESC, confidence DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return {
        "symbol": row[0],
        "direction": row[1],
        "confidence": row[2],
        "magnitude": row[3],
        "horizon": row[4],
        "pcs_score": row[5],
        "cts_score": row[6],
    }


def _get_producer_signals(db: Database, top_call: dict[str, Any] | None) -> list[dict[str, Any]]:
    cutoff = (datetime.now(tz=UTC) - timedelta(minutes=30)).isoformat()
    rows = db.execute(
        "SELECT payload FROM events WHERE type = ? AND ts >= ? ORDER BY ts DESC",
        # Plato's cave upgrade: read the fire (forecasts), not the shadows (accepted signals).
        ("forecast.v1", cutoff),
    ).fetchall()

    seen: dict[str, dict[str, Any]] = {}
    for r in rows:
        p = json.loads(r[0]) if isinstance(r[0], str) else r[0]

        action = p.get("action", "no_forecast")
        abstention = p.get("abstention_reason")

        # Skip abstention rows (action=no_forecast + abstention_reason set)
        if action == "no_forecast" and abstention is not None:
            continue

        # Extract producer id: strip @version suffix from source
        source = p.get("source", "unknown")
        # A monk signs name@monastery. The monastery changes; the hand does not.
        pid = source.split("@")[0] if "@" in source else source
        if pid in seen:
            continue

        direction = "neutral" if action == "no_forecast" else action
        confidence = float(p.get("confidence", 0.0))
        domain = p.get("asset", "unknown")

        # Lookup karma
        karma_row = db.fetchone("SELECT karma_score FROM producer_karma WHERE producer_id = ?", (pid,))
        karma_score = float(karma_row[0]) if karma_row else 1.0

        agrees = top_call is not None and direction == top_call.get("direction")

        seen[pid] = {
            "producer_id": pid,
            "domain": domain,
            "direction": direction,
            "confidence": confidence,
            "karma_score": karma_score,
            "agrees": agrees,
        }

    result = list(seen.values())
    result.sort(key=lambda x: x["confidence"], reverse=True)
    return result


def _get_benchmarks(db: Database) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT producer_id, karma_score, win_count, loss_count, total_trades FROM producer_karma WHERE producer_id LIKE 'benchmark.%'"
    ).fetchall()
    out = []
    for r in rows:
        name = str(r[0]).replace("benchmark.", "")
        total = int(r[4] or 0)
        wins = int(r[2] or 0)
        win_rate = round(wins / total, 2) if total > 0 else None
        out.append(
            {
                "name": name,
                "direction": "—",
                "pnl_7d": 0.0,
                "win_rate": win_rate,
            }
        )
    return out


def _get_system_status(db: Database) -> dict[str, Any]:
    # Kill switch level
    ks_row = db.execute(
        "SELECT payload FROM events WHERE type = ? ORDER BY ts DESC LIMIT 1",
        ("system.kill_switch.v1",),
    ).fetchone()
    ks_level = 0
    if ks_row:
        p = json.loads(ks_row[0]) if isinstance(ks_row[0], str) else ks_row[0]
        ks_level = int(p.get("level", 0))
    ks_name = _KS_LEVEL_NAMES.get(ks_level, "SAFE")

    # Consecutive losses
    loss_rows = db.fetchall("SELECT realized_pnl FROM positions WHERE status = 'closed' ORDER BY closed_at DESC LIMIT 10")
    consecutive_losses = 0
    for lr in loss_rows:
        if lr[0] is not None and float(lr[0]) < 0:
            consecutive_losses += 1
        else:
            break

    # Open positions
    open_rows = db.fetchall("SELECT asset, direction, entry_price, size_notional FROM positions WHERE status = 'open'")
    open_positions = [{"symbol": r[0], "direction": r[1], "entry": r[2], "unrealized_pnl": 0.0} for r in open_rows]

    open_risk_pct = 0.0

    # Last cycle
    cycle_row = db.execute(
        "SELECT ts FROM events WHERE type = ? ORDER BY ts DESC LIMIT 1",
        ("brain.conviction.v1",),
    ).fetchone()
    last_cycle_ts = cycle_row[0] if cycle_row else None

    return {
        "kill_switch_level": ks_name,
        "kill_switch_level_num": ks_level,
        "consecutive_losses": consecutive_losses,
        "open_risk_pct": open_risk_pct,
        "open_positions": open_positions,
        "last_cycle_ts": last_cycle_ts,
    }


@router.get("/cockpit/state")
def cockpit_state(db: Database = Depends(get_db)) -> dict[str, Any]:
    top_call = _get_top_call(db)
    producer_signals = _get_producer_signals(db, top_call)
    benchmarks = _get_benchmarks(db)
    system = _get_system_status(db)
    return {
        "top_call": top_call,
        "producer_signals": producer_signals,
        "benchmarks": benchmarks,
        "system": system,
    }
