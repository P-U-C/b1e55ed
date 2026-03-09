"""api.routes.outcomes

GET /api/v1/outcomes/{forecast_id}
  → Returns the outcome JSON for a resolved forecast (ERC-8004 fileURI target).
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends

from api.deps import get_db
from api.errors import B1e55edError
from engine.core.database import Database

router = APIRouter(prefix="/outcomes")


@router.get("/{forecast_id}")
def get_outcome(forecast_id: str, db: Database = Depends(get_db)) -> dict:
    """Return the outcome JSON for a resolved forecast.

    This is the target of the ERC-8004 fileURI stored on-chain.
    Joins forecast_resolution_state with events to build the response.
    """
    # Check resolution state
    resolution = db.execute(
        """
        SELECT forecast_event_id, resolved_at, outcome_event_id
        FROM forecast_resolution_state
        WHERE forecast_event_id = ?
        """,
        (forecast_id,),
    ).fetchone()

    if resolution is None:
        raise B1e55edError(
            status_code=404,
            code="outcome_not_found",
            message=f"No resolved outcome for forecast {forecast_id}",
        )

    # Fetch outcome event payload
    outcome_event = db.execute(
        "SELECT payload, ts, source FROM events WHERE id = ?",
        (str(resolution["outcome_event_id"]),),
    ).fetchone()

    if outcome_event is None:
        raise B1e55edError(
            status_code=404,
            code="outcome_event_missing",
            message=f"Outcome event {resolution['outcome_event_id']} not found",
        )

    payload = json.loads(str(outcome_event["payload"]))

    # Fetch conviction score if available
    conviction = None
    try:
        conv_row = db.execute(
            """
            SELECT cs.symbol, cs.direction, cs.magnitude, cs.confidence, cs.regime, cs.ts
            FROM conviction_scores cs
            JOIN events e ON e.source LIKE '%' || cs.node_id || '%'
            WHERE e.id = ?
            LIMIT 1
            """,
            (forecast_id,),
        ).fetchone()
        if conv_row:
            conviction = {
                "symbol": conv_row["symbol"],
                "direction": conv_row["direction"],
                "magnitude": conv_row["magnitude"],
                "confidence": conv_row["confidence"],
                "regime": conv_row["regime"],
                "scored_at": conv_row["ts"],
            }
    except Exception:
        pass  # Best-effort conviction lookup

    # Check karma chain queue for on-chain status
    chain_status = None
    try:
        chain_row = db.execute(
            "SELECT status, tx_hash, submitted_at FROM karma_chain_queue WHERE forecast_id = ? LIMIT 1",
            (forecast_id,),
        ).fetchone()
        if chain_row:
            chain_status = {
                "status": chain_row["status"],
                "tx_hash": chain_row["tx_hash"],
                "submitted_at": chain_row["submitted_at"],
            }
    except Exception:
        pass  # Best-effort chain status lookup

    return {
        "forecast_id": forecast_id,
        "resolved_at": resolution["resolved_at"],
        "outcome_event_id": str(resolution["outcome_event_id"]),
        "outcome": payload,
        "conviction": conviction,
        "chain": chain_status,
    }
