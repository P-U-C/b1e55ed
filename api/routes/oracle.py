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
    chain_verified: bool  # Backwards compat; see chain_integrity_spot_checked
    chain_integrity_spot_checked: bool  # Last 100 events verified against hash chain
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
        chain_integrity_spot_checked=result.chain_integrity_spot_checked,
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


# ---------------------------------------------------------------------------
# Public contributor registration — no auth required.
# The oracle holds the GitHub App key; new installs call this to get
# their registration issue created without needing credentials.
# ---------------------------------------------------------------------------


class ContributorRegisterOracleRequest(BaseModel):
    node_id: str
    name: str = ""
    role: str = "contributor"


class ContributorRegisterOracleResponse(BaseModel):
    contributor_id: str
    node_id: str
    name: str
    role: str
    registered_at: str
    issue_url: str | None = None


@router.post("/contributors/register", response_model=ContributorRegisterOracleResponse)
def oracle_register_contributor(
    req: ContributorRegisterOracleRequest,
    request: Request,
    db: Database = Depends(get_db),
) -> ContributorRegisterOracleResponse:
    """Public endpoint — registers a new contributor and creates a GitHub issue.

    Called by ``b1e55ed wizard`` on new installs.  No authentication required.
    The oracle supplies GitHub App credentials server-side so installers don't
    need a token.
    """
    from api.deps import get_publisher
    from engine.core.contributors import ContributorRegistry

    if not req.node_id.startswith("eth:0xb1e55ed"):
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="node_id must start with eth:0xb1e55ed")

    name = req.name or req.node_id
    publisher = get_publisher(request)
    reg = ContributorRegistry(db, github_publisher=publisher)

    try:
        c = reg.register(node_id=req.node_id, name=name, role=req.role)
    except ValueError:
        # Already registered — look up and return existing
        existing = next((x for x in reg.list_all() if x.node_id == req.node_id), None)
        if existing:
            issue_url = None
            pub = (existing.metadata.get("publish") or {}).get("github") if isinstance(existing.metadata, dict) else None
            if isinstance(pub, dict):
                issue_url = pub.get("html_url")
            return ContributorRegisterOracleResponse(
                contributor_id=existing.id,
                node_id=existing.node_id,
                name=existing.name,
                role=existing.role,
                registered_at=existing.registered_at,
                issue_url=issue_url,
            )
        from fastapi import HTTPException

        raise HTTPException(status_code=409, detail="contributor already registered") from None

    new_issue_url: str | None = None
    pub = (c.metadata.get("publish") or {}).get("github") if isinstance(c.metadata, dict) else None
    if isinstance(pub, dict):
        new_issue_url = pub.get("html_url")

    return ContributorRegisterOracleResponse(
        contributor_id=c.id,
        node_id=c.node_id,
        name=c.name,
        role=c.role,
        registered_at=c.registered_at,
        issue_url=new_issue_url,
    )
