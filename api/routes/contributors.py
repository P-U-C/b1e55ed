from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from api.auth import AuthDep
from api.deps import get_db, get_publisher
from api.errors import B1e55edError
from engine.core.contributors import Contributor, ContributorRegistry
from engine.core.database import Database
from engine.core.scoring import ContributorScoring


class ContributorAttestationResponse(BaseModel):
    contributor_id: str
    uid: str
    attestation: dict[str, Any]
    published: dict[str, Any] | None = None


class ContributorAttestationSummaryResponse(BaseModel):
    contributor_id: str
    node_id: str
    uid: str


router = APIRouter(prefix="/contributors", dependencies=[AuthDep])


class ContributorRegisterRequest(BaseModel):
    node_id: str = Field(..., description="Cryptographic node identity")
    name: str = Field(..., description="Display name")
    role: str = Field(..., description="operator|agent|tester|curator")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContributorResponse(BaseModel):
    id: str
    node_id: str
    name: str
    role: str
    registered_at: str
    metadata: dict[str, Any]
    published: bool | None = None

    @classmethod
    def from_contributor(cls, c: Contributor, *, published: bool | None = None) -> ContributorResponse:
        # If caller doesn't override, derive from metadata (True if github publish succeeded, else None)
        if published is None:
            pub_github = (c.metadata.get("publish") or {}).get("github")
            published = True if pub_github else None
        return cls(
            id=c.id,
            node_id=c.node_id,
            name=c.name,
            role=c.role,
            registered_at=c.registered_at,
            metadata=dict(c.metadata),
            published=published,
        )


class ContributorScoreResponse(BaseModel):
    contributor_id: str
    signals_submitted: int
    signals_accepted: int
    signals_profitable: int
    signals_resolved: int = 0
    hit_rate: float
    acceptance_rate: float = 0.0
    brier_score: float = 0.25
    avg_conviction: float
    total_karma_usd: float
    score: float
    last_active: str
    streak: int


@router.get("/", response_model=list[ContributorResponse])
def list_contributors(
    db: Database = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ContributorResponse]:
    rows = db.execute(
        "SELECT id, node_id, name, role, registered_at, metadata FROM contributors ORDER BY registered_at ASC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    import json as _json

    from engine.core.contributors import Contributor

    results = []
    for r in rows:
        meta = r[5]
        try:
            meta = _json.loads(meta) if isinstance(meta, str) else (meta or {})
        except Exception:
            meta = {}
        c = Contributor(id=str(r[0]), node_id=str(r[1]), name=str(r[2]), role=str(r[3]), registered_at=str(r[4]), metadata=meta)
        results.append(ContributorResponse.from_contributor(c))
    return results


@router.get("/attestations", response_model=list[ContributorAttestationSummaryResponse])
def list_attestations(db: Database = Depends(get_db)) -> list[ContributorAttestationSummaryResponse]:
    reg = ContributorRegistry(db)
    out: list[ContributorAttestationSummaryResponse] = []
    for c in reg.list_all():
        eas_meta = c.metadata.get("eas") if isinstance(c.metadata, dict) else None
        if not isinstance(eas_meta, dict):
            continue
        uid = str(eas_meta.get("uid") or "")
        if uid:
            out.append(ContributorAttestationSummaryResponse(contributor_id=c.id, node_id=c.node_id, uid=uid))
    return out


@router.get("/{contributor_id}/attestation", response_model=ContributorAttestationResponse)
def get_contributor_attestation(contributor_id: str, db: Database = Depends(get_db)) -> ContributorAttestationResponse:
    reg = ContributorRegistry(db)
    c = reg.get(contributor_id)
    if c is None:
        raise B1e55edError(code="contributor.not_found", message="Contributor not found", status=404, id=contributor_id)

    eas_meta = c.metadata.get("eas") if isinstance(c.metadata, dict) else None
    if not isinstance(eas_meta, dict) or not eas_meta.get("attestation"):
        raise B1e55edError(code="contributor.attestation_not_found", message="Attestation not found", status=404, id=contributor_id)

    att = eas_meta.get("attestation")
    if not isinstance(att, dict):
        raise B1e55edError(code="contributor.attestation_invalid", message="Attestation invalid", status=500, id=contributor_id)

    pub = eas_meta.get("publish")
    published: dict[str, Any] | None = pub if isinstance(pub, dict) else None
    return ContributorAttestationResponse(
        contributor_id=contributor_id,
        uid=str(eas_meta.get("uid") or ""),
        attestation=att,
        published=published,
    )


@router.post("/register", response_model=ContributorResponse)
def register_contributor(
    req: ContributorRegisterRequest,
    db: Database = Depends(get_db),
    publisher: object | None = Depends(get_publisher),
) -> ContributorResponse:
    reg = ContributorRegistry(db, github_publisher=publisher)
    try:
        c = reg.register(node_id=req.node_id, name=req.name, role=req.role, metadata=req.metadata)
    except ValueError as e:
        raise B1e55edError(
            code="contributor.duplicate",
            message="Contributor with node_id already exists",
            status=409,
            node_id=req.node_id,
        ) from e
    # Determine published: True if github publish succeeded, False if publisher configured but failed, None if not configured
    if publisher is not None:
        pub_github = (c.metadata.get("publish") or {}).get("github")
        reg_published: bool | None = bool(pub_github)
    else:
        reg_published = None
    return ContributorResponse.from_contributor(c, published=reg_published)


@router.get("/leaderboard", response_model=list[ContributorScoreResponse])
def leaderboard(
    db: Database = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=200),
) -> list[ContributorScoreResponse]:
    scoring = ContributorScoring(db)
    return [ContributorScoreResponse(**asdict(s)) for s in scoring.leaderboard(limit=limit)]


@router.get("/{contributor_id}/score", response_model=ContributorScoreResponse)
def contributor_score(contributor_id: str, db: Database = Depends(get_db)) -> ContributorScoreResponse:
    reg = ContributorRegistry(db)
    if reg.get(contributor_id) is None:
        raise B1e55edError(code="contributor.not_found", message="Contributor not found", status=404, id=contributor_id)

    scoring = ContributorScoring(db)
    s = scoring.compute_score(contributor_id)
    return ContributorScoreResponse(**asdict(s))


@router.get("/{contributor_id}/signals")
def list_contributor_signals(
    contributor_id: str,
    accepted: bool | None = Query(default=None, description="Filter by accepted status"),
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0),
    db: Database = Depends(get_db),
) -> dict:
    """List signals submitted by a contributor with their acceptance/rejection status."""
    query = """
        SELECT cs.event_id, cs.signal_asset, cs.accepted, cs.profitable,
               cs.created_at AS submitted_at, e.payload
        FROM contributor_signals cs
        LEFT JOIN events e ON e.id = cs.event_id
        WHERE cs.contributor_id = ?
    """
    params: list = [contributor_id]
    if accepted is not None:
        query += " AND cs.accepted = ?"
        params.append(1 if accepted else 0)
    query += " ORDER BY cs.created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = db.execute(query, params).fetchall()
    return {
        "contributor_id": contributor_id,
        "signals": [dict(r) for r in rows],
        "count": len(rows),
        "limit": limit,
        "offset": offset,
    }


@router.get("/{contributor_id}", response_model=ContributorResponse)
def get_contributor(contributor_id: str, db: Database = Depends(get_db)) -> ContributorResponse:
    reg = ContributorRegistry(db)
    c = reg.get(contributor_id)
    if c is None:
        raise B1e55edError(code="contributor.not_found", message="Contributor not found", status=404, id=contributor_id)
    return ContributorResponse.from_contributor(c)


@router.delete("/{contributor_id}")
def deregister_contributor(contributor_id: str, db: Database = Depends(get_db)) -> dict[str, str]:
    reg = ContributorRegistry(db)
    ok = reg.deregister(contributor_id)
    if not ok:
        raise B1e55edError(code="contributor.not_found", message="Contributor not found", status=404, id=contributor_id)
    return {"removed": contributor_id}
