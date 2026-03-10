"""Chain registration status endpoint.

Returns the on-chain registration state, karma balance, and threshold info
so the dashboard and external consumers can render registration prompts.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from api.auth import AuthDep
from api.deps import get_config, get_db
from engine.core.config import Config
from engine.core.database import Database

router = APIRouter(dependencies=[AuthDep])


@router.get("/chain/registration-status")
def registration_status(
    config: Config = Depends(get_config),
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    """Return on-chain registration state for the running node."""
    agent_id = config.onchain.system_agent_id
    registered = agent_id != 0

    # Total karma earned
    row = db.execute("SELECT COALESCE(SUM(karma_amount_usd), 0) FROM karma_intents").fetchone()
    karma_balance = float(row[0]) if row else 0.0

    threshold = config.karma.registration_threshold
    threshold_reached = karma_balance >= threshold

    # Agent vs human heuristic: if public_base_url is set, treat as agent node
    is_agent = bool(config.onchain.public_base_url)

    chain_configured = bool(config.onchain.enabled and config.onchain.identity_registry_address)

    return {
        "registered": registered,
        "agent_id": agent_id,
        "karma_balance": round(karma_balance, 4),
        "threshold": threshold,
        "threshold_reached": threshold_reached,
        "is_agent": is_agent,
        "chain_configured": chain_configured,
    }
