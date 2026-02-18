from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends

from api.auth import AuthDep
from api.deps import get_config, get_db, get_kill_switch
from api.schemas.brain import BrainStatus, CycleResult
from engine.brain.kill_switch import KillSwitch
from engine.brain.orchestrator import BrainOrchestrator
from engine.core.config import Config
from engine.core.database import Database
from engine.security import generate_node_identity

router = APIRouter(prefix="/brain", dependencies=[AuthDep])


def _parse_dt(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except Exception:
        return None


@router.get("/status", response_model=BrainStatus)
def status(
    db: Database = Depends(get_db),
    ks: KillSwitch = Depends(get_kill_switch),
) -> BrainStatus:
    # Last regime change
    regime = None
    regime_at = None
    row = db.conn.execute(
        "SELECT payload, ts FROM events WHERE type = ? ORDER BY ts DESC LIMIT 1",
        ("brain.regime_change.v1",),
    ).fetchone()
    if row is not None:
        payload = json.loads(str(row[0]))
        regime = payload.get("regime") or payload.get("state") or payload.get("name")
        regime_at = _parse_dt(str(row[1]))

    # Last kill switch change
    ks_row = db.conn.execute(
        "SELECT payload, ts FROM events WHERE type = ? ORDER BY ts DESC LIMIT 1",
        ("system.kill_switch.v1",),
    ).fetchone()
    ks_reason = None
    ks_at = None
    if ks_row is not None:
        payload = json.loads(str(ks_row[0]))
        ks_reason = payload.get("reason")
        ks_at = _parse_dt(str(ks_row[1]))

    # Last cycle marker
    cycle_row = db.conn.execute(
        "SELECT payload, ts FROM events WHERE type = ? ORDER BY ts DESC LIMIT 1",
        ("brain.cycle.v1",),
    ).fetchone()
    last_cycle_id = None
    last_cycle_at = None
    if cycle_row is not None:
        payload = json.loads(str(cycle_row[0]))
        last_cycle_id = payload.get("cycle_id")
        last_cycle_at = _parse_dt(str(cycle_row[1]))

    return BrainStatus(
        regime=regime,
        regime_changed_at=regime_at,
        kill_switch_level=int(ks.level),
        kill_switch_reason=ks_reason,
        kill_switch_changed_at=ks_at,
        last_cycle_id=last_cycle_id,
        last_cycle_at=last_cycle_at,
    )


@router.post("/run", response_model=CycleResult)
def run_cycle(
    config: Config = Depends(get_config),
    db: Database = Depends(get_db),
) -> CycleResult:
    # Create orchestrator with ephemeral identity (API tests override if needed)
    identity = generate_node_identity()
    orch = BrainOrchestrator(config=config, db=db, identity=identity)
    res = orch.run_cycle(symbols=list(config.universe.symbols))

    kill_level = None
    try:
        kill_level = int(orch.kill_switch.level)
    except Exception:
        kill_level = None

    regime = None
    try:
        regime = str(res.regime.state.regime)
    except Exception:
        regime = None

    return CycleResult(
        cycle_id=res.cycle_id,
        ts=res.ts,
        intents=res.intents,
        regime=regime,
        kill_switch_level=kill_level,
    )
