from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from api.auth import AuthDep
from api.deps import get_config, get_db, get_karma
from api.errors import B1e55edError
from engine.core.config import Config
from engine.core.database import Database
from engine.execution.karma import KarmaEngine

router = APIRouter(dependencies=[AuthDep])


@router.get("/treasury")
def treasury(config: Config = Depends(get_config), db: Database = Depends(get_db)) -> dict[str, Any]:
    pending = db.fetchone("SELECT COUNT(1) FROM karma_intents WHERE settled = 0")
    pending_n = int(pending[0]) if pending is not None else 0

    receipts = db.fetchone("SELECT COUNT(1) FROM karma_settlements")
    receipts_n = int(receipts[0]) if receipts is not None else 0

    return {
        "enabled": bool(config.karma.enabled),
        "percentage": float(config.karma.percentage),
        "treasury_address": str(config.karma.treasury_address),
        "pending_intents": pending_n,
        "receipts": receipts_n,
    }


@router.get("/karma/intents")
def karma_intents(
    karma: KarmaEngine = Depends(get_karma),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    return {"items": [i.__dict__ for i in karma.get_pending_intents(limit=limit, offset=offset)]}


@router.post("/karma/settle")
def karma_settle(
    payload: dict[str, Any],
    karma: KarmaEngine = Depends(get_karma),
) -> dict[str, Any]:
    intent_ids = payload.get("intent_ids")
    if not isinstance(intent_ids, list) or not all(isinstance(x, str) for x in intent_ids):
        raise B1e55edError(code="invalid_request", message="intent_ids must be a list of strings", status=400)

    tx_hash = payload.get("tx_hash")
    receipt = karma.settle(intent_ids=[str(x) for x in intent_ids], tx_hash=str(tx_hash) if tx_hash else None)
    if receipt is None:
        raise B1e55edError(code="settlement_failed", message="Settlement not recorded", status=400)

    return {"receipt": receipt.__dict__}


@router.get("/karma/receipts")
def karma_receipts(karma: KarmaEngine = Depends(get_karma)) -> dict[str, Any]:
    return {"items": [r.__dict__ for r in karma.get_receipts()]}
