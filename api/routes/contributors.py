from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.auth import AuthDep
from api.deps import get_db
from api.errors import B1e55edError
from engine.core.contributors import Contributor, ContributorRegistry
from engine.core.database import Database
from engine.core.scoring import ContributorScoring


class ContributorAttestationResponse(BaseModel):
    contributor_id: str
    uid: str
    attestation: dict[str, Any]


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

    @classmethod
    def from_contributor(cls, c: Contributor) -> ContributorResponse:
        return cls(
            id=c.id,
            node_id=c.node_id,
            name=c.name,
            role=c.role,
            registered_at=c.registered_at,
            metadata=dict(c.metadata),
        )


class ContributorScoreResponse(BaseModel):
    contributor_id: str
    signals_submitted: int
    signals_accepted: int
    signals_profitable: int
    hit_rate: float
    avg_conviction: float
    total_karma_usd: float
    score: float
    last_active: str
    streak: int


@router.get("/", response_model=list[ContributorResponse])
def list_contributors(db: Database = Depends(get_db)) -> list[ContributorResponse]:
    reg = ContributorRegistry(db)
    return [ContributorResponse.from_contributor(c) for c in reg.list_all()]


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

    return ContributorAttestationResponse(contributor_id=contributor_id, uid=str(eas_meta.get("uid") or ""), attestation=att)


@router.post("/register", response_model=ContributorResponse)
def register_contributor(req: ContributorRegisterRequest, db: Database = Depends(get_db)) -> ContributorResponse:
    reg = ContributorRegistry(db)
    try:
        c = reg.register(node_id=req.node_id, name=req.name, role=req.role, metadata=req.metadata)
    except ValueError as e:
        raise B1e55edError(
            code="contributor.duplicate",
            message="Contributor with node_id already exists",
            status=409,
            node_id=req.node_id,
        ) from e
    return ContributorResponse.from_contributor(c)


@router.get("/leaderboard", response_model=list[ContributorScoreResponse])
def leaderboard(db: Database = Depends(get_db), limit: int = 20) -> list[ContributorScoreResponse]:
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
