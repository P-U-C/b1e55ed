from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.auth import AuthDep
from api.deps import get_db, get_registry
from api.errors import B1e55edError
from engine.core.database import Database
from engine.security.ssrf import check_url

router = APIRouter(prefix="/producers", dependencies=[AuthDep])


def _parse_dt(ts: str | None) -> datetime | None:
    if not ts:
        return None
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _ensure_endpoint_column(db: Database) -> None:
    cols = [str(r[1]) for r in db.conn.execute("PRAGMA table_info(producer_health)").fetchall()]
    if "endpoint" in cols:
        return
    with db.conn:
        db.conn.execute("ALTER TABLE producer_health ADD COLUMN endpoint TEXT")


class ProducerRegistration(BaseModel):
    name: str = Field(..., description="Unique producer name")
    domain: str = Field(
        ...,
        description="Signal domain: technical, sentiment, onchain, macro, social",
    )
    endpoint: str = Field(..., description="URL to poll for signals")
    schedule: str = Field("*/15 * * * *", description="Cron schedule for polling")


class ProducerResponse(BaseModel):
    name: str
    domain: str
    endpoint: str
    schedule: str
    registered_at: str


class ProducerHealth(BaseModel):
    name: str
    domain: str | None = None
    schedule: str | None = None
    endpoint: str | None = None
    healthy: bool | None = None
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    events_produced: int = 0
    avg_duration_ms: float | None = None
    expected_interval_ms: int | None = None
    updated_at: datetime | None = None


class ProducerStatusResponse(BaseModel):
    producers: dict[str, ProducerHealth]


@router.get("/status", response_model=ProducerStatusResponse)
def producer_status(
    db: Database = Depends(get_db),
    registry=Depends(get_registry),
) -> ProducerStatusResponse:
    _ensure_endpoint_column(db)

    names = registry.list_producers()
    out: dict[str, ProducerHealth] = {}

    for name in names:
        row = db.conn.execute(
            """
            SELECT name, domain, schedule, endpoint, last_run_at, last_success_at, last_error,
                   consecutive_failures, events_produced, avg_duration_ms, expected_interval_ms, updated_at
            FROM producer_health
            WHERE name = ?
            """,
            (name,),
        ).fetchone()

        if row is None:
            out[name] = ProducerHealth(
                name=name,
                domain=getattr(registry.get_producer(name), "domain", None),
                healthy=None,
                last_run_at=None,
                last_success_at=None,
                last_error=None,
                consecutive_failures=0,
                events_produced=0,
            )
            continue

        consecutive_failures = int(row[7]) if row[7] is not None else 0
        last_error = str(row[6]) if row[6] is not None else None
        healthy = consecutive_failures == 0 and last_error is None

        out[name] = ProducerHealth(
            name=str(row[0]),
            domain=str(row[1]) if row[1] is not None else None,
            schedule=str(row[2]) if row[2] is not None else None,
            endpoint=str(row[3]) if row[3] is not None else None,
            healthy=healthy,
            last_run_at=_parse_dt(str(row[4])) if row[4] is not None else None,
            last_success_at=_parse_dt(str(row[5])) if row[5] is not None else None,
            last_error=last_error,
            consecutive_failures=consecutive_failures,
            events_produced=int(row[8]) if row[8] is not None else 0,
            avg_duration_ms=float(row[9]) if row[9] is not None else None,
            expected_interval_ms=int(row[10]) if row[10] is not None else None,
            updated_at=_parse_dt(str(row[11])) if row[11] is not None else None,
        )

    return ProducerStatusResponse(producers=out)


@router.post("/register", response_model=ProducerResponse)
def register_producer(reg: ProducerRegistration, db: Database = Depends(get_db)) -> ProducerResponse:
    _ensure_endpoint_column(db)

    # SSRF protection (PH1)
    url_check = check_url(reg.endpoint)
    if not url_check.allowed:
        raise B1e55edError(
            code="producer.endpoint_blocked",
            message=f"Endpoint blocked: {url_check.reason}",
            status=400,
            endpoint=reg.endpoint,
        )

    now = datetime.now(tz=UTC).isoformat()

    existing = db.conn.execute(
        "SELECT name FROM producer_health WHERE name = ?",
        (reg.name,),
    ).fetchone()
    if existing is not None:
        raise B1e55edError(
            code="producer.duplicate",
            message="Producer already registered",
            status=409,
            name=reg.name,
        )

    with db.conn:
        db.conn.execute(
            """
            INSERT INTO producer_health (name, domain, schedule, endpoint, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (reg.name, reg.domain, reg.schedule, reg.endpoint, now),
        )

    return ProducerResponse(
        name=reg.name,
        domain=reg.domain,
        endpoint=reg.endpoint,
        schedule=reg.schedule,
        registered_at=now,
    )


@router.delete("/{name}")
def deregister_producer(name: str, db: Database = Depends(get_db)) -> dict[str, str]:
    _ensure_endpoint_column(db)

    with db.conn:
        cur = db.conn.execute(
            "DELETE FROM producer_health WHERE name = ?",
            (name,),
        )

    if cur.rowcount == 0:
        raise B1e55edError(
            code="producer.not_found",
            message="Producer not found",
            status=404,
            name=name,
        )

    return {"removed": name}


@router.get("/", response_model=dict)
def list_producers(db: Database = Depends(get_db)) -> dict[str, Any]:
    _ensure_endpoint_column(db)

    rows = db.conn.execute(
        """
        SELECT name, domain, schedule, endpoint, updated_at
        FROM producer_health
        ORDER BY name ASC
        """
    ).fetchall()

    producers: list[ProducerResponse] = []
    for r in rows:
        producers.append(
            ProducerResponse(
                name=str(r[0]),
                domain=str(r[1]) if r[1] is not None else "",
                schedule=str(r[2]) if r[2] is not None else "",
                endpoint=str(r[3]) if r[3] is not None else "",
                registered_at=str(r[4]) if r[4] is not None else "",
            )
        )

    return {"producers": producers}
