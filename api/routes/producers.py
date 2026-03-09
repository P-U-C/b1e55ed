from __future__ import annotations

from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
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
    cols = [str(r[1]) for r in db.execute("PRAGMA table_info(producer_health)").fetchall()]
    with db.conn:
        if "endpoint" not in cols:
            db.execute("ALTER TABLE producer_health ADD COLUMN endpoint TEXT")
        if "quarantined_until" not in cols:
            db.execute("ALTER TABLE producer_health ADD COLUMN quarantined_until TEXT")
        if "quarantined_reason" not in cols:
            db.execute("ALTER TABLE producer_health ADD COLUMN quarantined_reason TEXT")


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
    quarantined_until: datetime | None = None
    quarantined_reason: str | None = None
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
        row = db.execute(
            """
            SELECT name, domain, schedule, endpoint, quarantined_until, quarantined_reason, last_run_at, last_success_at, last_error,
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

        quarantined_until = _parse_dt(str(row[4])) if row[4] is not None else None
        quarantined_reason = str(row[5]) if row[5] is not None else None
        last_run_at = _parse_dt(str(row[6])) if row[6] is not None else None
        last_success_at = _parse_dt(str(row[7])) if row[7] is not None else None
        last_error = str(row[8]) if row[8] is not None else None
        consecutive_failures = int(row[9]) if row[9] is not None else 0

        now = datetime.now(tz=UTC)
        quarantined = quarantined_until is not None and quarantined_until > now
        healthy = (consecutive_failures == 0 and last_error is None) and not quarantined

        out[name] = ProducerHealth(
            name=str(row[0]),
            domain=str(row[1]) if row[1] is not None else None,
            schedule=str(row[2]) if row[2] is not None else None,
            endpoint=str(row[3]) if row[3] is not None else None,
            healthy=healthy,
            quarantined_until=quarantined_until,
            quarantined_reason=quarantined_reason,
            last_run_at=last_run_at,
            last_success_at=last_success_at,
            last_error=last_error,
            consecutive_failures=consecutive_failures,
            events_produced=int(row[10]) if row[10] is not None else 0,
            avg_duration_ms=float(row[11]) if row[11] is not None else None,
            expected_interval_ms=int(row[12]) if row[12] is not None else None,
            updated_at=_parse_dt(str(row[13])) if row[13] is not None else None,
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

    existing = db.execute(
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
        db.execute(
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
        cur = db.execute(
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

    rows = db.execute(
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


# ---------------------------------------------------------------------------
# Producer Capability Discovery
# ---------------------------------------------------------------------------

# Domain → canonical signal event types emitted by that domain
_DOMAIN_SIGNAL_TYPES: dict[str, list[str]] = {
    "technical": ["signal.ta.v1"],
    "onchain": ["signal.onchain.v1", "signal.whale.v1", "signal.orderbook.v1"],
    "tradfi": ["signal.tradfi.v1", "signal.etf.v1"],
    "social": ["signal.social.v1", "signal.sentiment.v1", "signal.curator.v1"],
    "events": ["signal.events.v1"],
    "macro": ["signal.stablecoin.v1"],
    "aci": ["signal.aci.v1"],
    "price": ["signal.price_alert.v1", "signal.price_ws.v1"],
}


def _schema_for_event_type(event_type_str: str) -> dict[str, Any]:
    """Return the JSON schema for a known event type's payload, or {}."""
    from engine.core.events import _EVENT_PAYLOAD_MODELS, EventType  # noqa: PLC2701

    try:
        et = EventType(event_type_str)
        model = _EVENT_PAYLOAD_MODELS.get(et)
        if model is not None:
            return model.model_json_schema()
    except Exception:
        pass
    return {}


class SignalTypeCapability(BaseModel):
    name: str
    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")

    model_config = {"populate_by_name": True}


class ProducerCapability(BaseModel):
    producer_id: str
    signal_types: list[SignalTypeCapability]
    last_seen: str | None
    health: str  # "healthy" | "degraded" | "unknown"


@router.get("/capabilities", response_model=list[ProducerCapability])
def producer_capabilities(
    db: Database = Depends(get_db),
) -> list[ProducerCapability]:
    """List all registered producers with their signal types and schemas.

    Signal types are derived from the producer's domain.  The ``schema`` for
    each signal type is the JSON schema of the corresponding payload model.
    """
    _ensure_endpoint_column(db)

    rows = db.execute(
        """
        SELECT name, domain, last_success_at, consecutive_failures,
               last_run_at, quarantined_until, updated_at
        FROM producer_health
        ORDER BY name ASC
        """
    ).fetchall()

    result: list[ProducerCapability] = []
    now = datetime.now(tz=UTC)

    for r in rows:
        name = str(r[0])
        domain = str(r[1]) if r[1] is not None else ""
        last_success_at = str(r[2]) if r[2] is not None else None
        consecutive_failures = int(r[3]) if r[3] is not None else 0
        quarantined_until_raw = str(r[4]) if r[4] is not None else None

        # Determine health string
        quarantined = False
        if quarantined_until_raw:
            try:
                qu = datetime.fromisoformat(quarantined_until_raw.replace("Z", "+00:00"))
                if qu.tzinfo is None:
                    qu = qu.replace(tzinfo=UTC)
                quarantined = qu > now
            except Exception:
                pass

        if quarantined or consecutive_failures > 0:
            health = "degraded"
        elif last_success_at is not None:
            health = "healthy"
        else:
            health = "unknown"

        # Build signal type list from domain mapping, or fall back to events table
        signal_type_names: list[str] = _DOMAIN_SIGNAL_TYPES.get(domain, [])

        if not signal_type_names:
            # Look up event types this producer has actually emitted
            type_rows = db.execute(
                "SELECT DISTINCT type FROM events WHERE source = ? AND type LIKE 'signal.%' LIMIT 20",
                (name,),
            ).fetchall()
            signal_type_names = [str(tr[0]) for tr in type_rows]

        signal_types = [SignalTypeCapability(name=stn, **{"schema": _schema_for_event_type(stn)}) for stn in signal_type_names]

        result.append(
            ProducerCapability(
                producer_id=name,
                signal_types=signal_types,
                last_seen=last_success_at,
                health=health,
            )
        )

    return result


@router.post("/{name}/restart")
def restart_producer(name: str, db: Database = Depends(get_db)) -> dict[str, Any]:
    """Clear quarantine + failure state so the producer can run again."""
    try:
        db.execute(
            "UPDATE producers SET quarantine_until = NULL, consecutive_failures = 0 WHERE name = ?",
            (name,),
        )
        db.conn.commit()
        return {"ok": True, "producer": name, "action": "restart"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{name}/reset-failures")
def reset_producer_failures(name: str, db: Database = Depends(get_db)) -> dict[str, Any]:
    """Reset consecutive failure count for a producer."""
    try:
        db.execute(
            "UPDATE producers SET consecutive_failures = 0 WHERE name = ?",
            (name,),
        )
        db.conn.commit()
        return {"ok": True, "producer": name, "action": "reset-failures"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{name}/run-now")
def run_producer_now(name: str, db: Database = Depends(get_db)) -> dict[str, Any]:
    """Trigger an immediate producer run (marks it for next scheduler tick)."""
    try:
        db.execute(
            "UPDATE producers SET next_run_at = datetime('now') WHERE name = ?",
            (name,),
        )
        db.conn.commit()
        return {"ok": True, "producer": name, "action": "run-now"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
