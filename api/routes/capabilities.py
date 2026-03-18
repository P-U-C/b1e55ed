"""api.routes.capabilities

Consolidated capability discovery endpoint for agent onboarding.

GET /api/v1/capabilities
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.auth import AuthDep
from api.deps import get_db
from api.routes.mcp import TOOLS
from api.routes.producers import ProducerCapability, producer_capabilities
from engine.core.database import Database

router = APIRouter(dependencies=[AuthDep])

_DEFAULT_EVENT_DOMAINS = {"alert", "learning", "signal", "system"}


class ToolCapability(BaseModel):
    name: str
    description: str


class CapabilitiesResponse(BaseModel):
    tools: list[ToolCapability]
    event_domains: list[str]
    producers: list[ProducerCapability]


def _derive_event_domains(db: Database, producers: list[ProducerCapability]) -> list[str]:
    domains = set(_DEFAULT_EVENT_DOMAINS)

    for producer in producers:
        for signal_type in producer.signal_types:
            if signal_type.name:
                domains.add(signal_type.name.split(".", 1)[0])

    # Include other domain prefixes observed in recent events (best-effort).
    try:
        rows = db.execute("SELECT DISTINCT type FROM events ORDER BY ts DESC LIMIT 500").fetchall()
    except Exception:
        rows = []

    for row in rows:
        event_type = str(row[0]) if row and row[0] is not None else ""
        if not event_type or "." not in event_type:
            continue
        domains.add(event_type.split(".", 1)[0].lower())

    return sorted(domains)


@router.get("/capabilities", response_model=CapabilitiesResponse)
def get_capabilities(db: Database = Depends(get_db)) -> CapabilitiesResponse:
    """Return supported tools, event domains, and producer capability data."""

    producers = producer_capabilities(db)
    tools = [ToolCapability(name=str(tool.get("name")), description=str(tool.get("description") or "")) for tool in TOOLS if tool.get("name")]

    return CapabilitiesResponse(
        tools=tools,
        event_domains=_derive_event_domains(db, producers),
        producers=producers,
    )
