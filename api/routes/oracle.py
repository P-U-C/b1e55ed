"""api.routes.oracle

Public-facing provenance oracle.  No authentication required — this is
intentionally open so any agent can verify producer lineage before acting
on a signal.

ANTI-GOODHART NOTICE (enforced via response header):
  These fields are informational only.  Optimizing against specific metrics
  will trigger drift detection.  The oracle updates continuously; scores can
  move against you after you lock in a position.

Endpoint:
    GET /oracle/producers/{producer_id}/provenance
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from api.deps import get_config, get_db
from engine.core.database import Database
from engine.core.oracle_query_log import log_oracle_query
from engine.core.provenance import compute_provenance

router = APIRouter()

_ANTI_GOODHART = "Fields informational only. May change without notice. Optimizing against specific metrics triggers drift detection."

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class AttributionWindow(BaseModel):
    signals: int
    hit_rate: float
    max_drawdown_pct: float


class ProvenanceResponse(BaseModel):
    producer_id: str
    has_provenance: bool
    chain_verified: bool
    total_signals: int
    p_and_l_attributed: bool
    operator_coverage: int
    first_seen: str | None
    last_seen: str | None
    attribution_windows: dict[str, AttributionWindow]
    note: str


class ProvenanceNotFoundResponse(BaseModel):
    producer_id: str
    has_provenance: bool = False
    note: str = "No provenance data available. Proceeding without attribution context."


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/producers/{producer_id}/provenance",
    response_model=ProvenanceResponse | ProvenanceNotFoundResponse,
    summary="Get producer provenance",
    description=(
        "Returns chain-verified history and coverage data for a signal producer. "
        "Does NOT return a trust score or recommendation — the caller decides "
        "what the data means. No authentication required."
    ),
    tags=["oracle"],
)
async def get_producer_provenance(
    producer_id: str,
    request: Request,
    response: Response,
    db: Database = Depends(get_db),
) -> ProvenanceResponse | ProvenanceNotFoundResponse:
    """Public provenance lookup for a signal producer."""

    # Always set the anti-Goodhart header so consumers know what they're
    # signing up for before they even read the body.
    response.headers["X-Attribution-Notice"] = _ANTI_GOODHART

    # Optional signal_type query param (passed through to logger only)
    signal_type: str | None = request.query_params.get("signal_type")

    result = compute_provenance(producer_id, db)

    # -----------------------------------------------------------------------
    # Anonymized demand logging (best-effort — never block the response)
    # -----------------------------------------------------------------------
    try:
        config = get_config(request)
        data_dir = config.data_dir
        log_oracle_query(
            producer_id=producer_id,
            signal_type=signal_type,
            has_provenance=result.has_provenance,
            data_dir=data_dir,
        )
    except Exception:
        pass  # Never let logging break the provenance response

    if not result.has_provenance:
        return ProvenanceNotFoundResponse(
            producer_id=result.producer_id,
            note=result.note,
        )

    return ProvenanceResponse(
        producer_id=result.producer_id,
        has_provenance=result.has_provenance,
        chain_verified=result.chain_verified,
        total_signals=result.total_signals,
        p_and_l_attributed=result.p_and_l_attributed,
        operator_coverage=result.operator_coverage,
        first_seen=result.first_seen,
        last_seen=result.last_seen,
        attribution_windows={
            k: AttributionWindow(
                signals=v.signals,
                hit_rate=v.hit_rate,
                max_drawdown_pct=v.max_drawdown_pct,
            )
            for k, v in result.attribution_windows.items()
        },
        note=result.note,
    )
