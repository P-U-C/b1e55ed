"""api.routes.agents

ERC-8004 compliant agent manifest endpoint.

GET /api/v1/agents/{node_id}/manifest
  → Returns the ERC-8004 registration JSON for a producer.

GET /.well-known/agent-registration.json
  → System-level agent manifest (wired directly in api/main.py).
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request

from api.deps import get_db
from api.errors import B1e55edError
from engine.core.database import Database

router = APIRouter(prefix="/agents")


def _build_manifest(
    *,
    node_id: str,
    name: str,
    role: str,
    description: str = "",
    api_base: str = "",
    agent_id: int | None = None,
    metadata: dict | None = None,
) -> dict:
    """Build an ERC-8004 compliant agent manifest."""
    manifest: dict = {
        "type": "https://github.com/P-U-C/b1e55ed/blob/main/docs/specs/erc-8004-agent-registration.md#registration-v1",
        "name": name,
        "description": description or f"b1e55ed producer: {name}",
        "url": f"{api_base}/api/v1/agents/{node_id}/manifest" if api_base else "",
        "capabilities": {
            "signals": True,
            "forecasts": True,
        },
        "identity": {
            "node_id": node_id,
            "role": role,
        },
        "trust": {
            "type": "b1e55ed-karma",
            "provenance_url": f"{api_base}/api/v1/oracle/producers/{node_id}/provenance" if api_base else "",
        },
    }
    if agent_id is not None:
        manifest["identity"]["agent_id"] = agent_id
    if metadata:
        manifest["metadata"] = metadata
    return manifest


@router.get("/{node_id}/manifest")
def get_agent_manifest(
    node_id: str,
    request: Request,
    db: Database = Depends(get_db),
) -> dict:
    """Return ERC-8004-compliant agent manifest for a producer."""
    # Query contributor row without assuming optional columns exist.
    # Some deployments do not have an `agent_id` column in contributors.
    row = db.execute(
        "SELECT * FROM contributors WHERE node_id = ?",
        (node_id,),
    ).fetchone()

    if row is None:
        raise B1e55edError(
            code="agent.not_found",
            message=f"No agent found with node_id: {node_id}",
            status=404,
            node_id=node_id,
        )

    # sqlite3.Row supports [] access but not .get(); use keys() to check column existence
    _keys = row.keys() if hasattr(row, "keys") else []
    col_names = list(_keys)
    meta_raw = row["metadata"] if "metadata" in col_names else "{}"
    try:
        meta = json.loads(meta_raw) if isinstance(meta_raw, str) else (meta_raw or {})
    except Exception:
        meta = {}

    agent_id_val = row["agent_id"] if "agent_id" in col_names else None

    api_base = str(request.base_url).rstrip("/")

    return _build_manifest(
        node_id=str(row["node_id"]),
        name=str(row["name"]),
        role=str(row["role"]),
        api_base=api_base,
        agent_id=int(agent_id_val) if agent_id_val is not None else None,
        metadata=meta,
    )


def build_system_manifest(api_base: str = "") -> dict:
    """Build the system-level /.well-known/agent-registration.json manifest."""
    oracle_base = "https://oracle.b1e55ed.permanentupperclass.com"
    return {
        "type": "https://github.com/P-U-C/b1e55ed/blob/main/docs/specs/erc-8004-agent-registration.md#registration-v1",
        "name": "b1e55ed",
        "description": (
            "Falsifiable profit engine. Signal producers register, earn karma "
            "through outcome-weighted forecasts, and build on-chain reputation "
            "via ERC-8004 Identity + Reputation + Validation registries on "
            "Ethereum mainnet."
        ),
        "image": f"{oracle_base}/static/logo.png",
        "endpoints": [
            {
                "name": "oracle",
                "endpoint": f"{oracle_base}/api/v1",
                "version": "1.0.0",
            },
            {
                "name": "MCP",
                "endpoint": f"{oracle_base}/api/v1/mcp",
                "version": "2024-11-05",
            },
            {
                "name": "A2A",
                "endpoint": f"{oracle_base}/.well-known/agent-registration.json",
                "version": "0.3.0",
            },
        ],
        "supportedTrust": ["reputation", "validation"],
        "synthesis_participant": True,
        "synthesis_registration": f"POST {oracle_base}/api/v1/oracle/contributors/register",
        "links": {
            "docs": "https://docs.b1e55ed.permanentupperclass.com",
            "github": "https://github.com/P-U-C/b1e55ed",
            "oracle": oracle_base,
        },
    }


@router.get("/.well-known/agent-registration.json", include_in_schema=False)
async def well_known_agent_registration() -> dict:
    """Serve /.well-known/agent-registration.json (also mounted at app root)."""
    return build_system_manifest()
