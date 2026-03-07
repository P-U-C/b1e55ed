"""b1e55ed MCP Gateway — harness-agnostic FastAPI proxy with RBAC and signal approval.

Sits between any MCP client (DeerFlow, Claude, etc.) and b1e55ed's ``/mcp/call``
endpoint.  Provides per-user API-key auth, role-based tool filtering, a signal
approval queue for non-admin ``submit_research_signal`` calls, and a full audit
log.

Run with::

    uvicorn gateway.main:app --host 0.0.0.0 --port 7338
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("gateway")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_CONFIG_PATH = os.environ.get("GATEWAY_CONFIG", str(Path(__file__).parent / "config.yaml"))


def _load_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)


CFG = _load_config()
B1E55ED_URL: str = CFG["b1e55ed_url"].rstrip("/")
B1E55ED_TOKEN: str = CFG.get("b1e55ed_token", "")
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
PENDING_PATH = DATA_DIR / "pending_signals.jsonl"
AUDIT_PATH = DATA_DIR / "audit.jsonl"

# ---------------------------------------------------------------------------
# RBAC definitions
# ---------------------------------------------------------------------------
ROLE_HIERARCHY: dict[str, set[str]] = {
    "analyst": {
        "get_regime_status",
        "get_top_signals",
        "get_regime_history",
        "get_signals_bulk_export",
        "get_brain_status",
        "get_recent_signals",
    },
    "pm": set(),  # filled below
    "risk": set(),
    "admin": set(),
}
ROLE_HIERARCHY["pm"] = ROLE_HIERARCHY["analyst"] | {
    "get_open_positions",
    "get_signal_attribution",
}
ROLE_HIERARCHY["risk"] = ROLE_HIERARCHY["pm"] | {
    "b1e55ed_provenance_check",
}
ROLE_HIERARCHY["admin"] = ROLE_HIERARCHY["risk"] | {
    "submit_research_signal",
    "emit_producer_signal",
}

ALL_TOOLS = ROLE_HIERARCHY["admin"]

# Build user lookup
USERS: dict[str, dict] = {}
for u in CFG.get("users", []):
    USERS[u["api_key"]] = {"name": u["name"], "role": u["role"]}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _audit(user: str, role: str, tool: str, params: dict | None, status: str, detail: str = "") -> None:
    """Append an entry to the audit log."""
    entry = {
        "ts": _utcnow(),
        "user": user,
        "role": role,
        "tool": tool,
        "params": _redact(params) if params else None,
        "status": status,
        "detail": detail,
    }
    with open(AUDIT_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _redact(params: dict | None) -> dict:
    """Remove potentially sensitive long values from audit params."""
    if not params:
        return {}
    out: dict[str, Any] = {}
    for k, v in params.items():
        if isinstance(v, str) and len(v) > 200:
            out[k] = v[:80] + "...<redacted>"
        else:
            out[k] = v
    return out


def _authenticate(api_key: str | None) -> dict:
    """Return user dict or raise 401."""
    if not api_key or api_key not in USERS:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return USERS[api_key]


def _allowed_tools(role: str) -> set[str]:
    return ROLE_HIERARCHY.get(role, set())


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="b1e55ed MCP Gateway", version="0.2.0")


class MCPRequest(BaseModel):
    """Minimal JSON-RPC envelope for MCP tool calls."""

    method: str = "tools/call"
    params: dict = {}
    id: Any = None
    jsonrpc: str = "2.0"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    """Gateway health + b1e55ed reachability probe."""
    reachable = False
    b1e55ed_status = "unknown"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            headers = {}
            if B1E55ED_TOKEN:
                headers["Authorization"] = f"Bearer {B1E55ED_TOKEN}"
            r = await client.get(f"{B1E55ED_URL}/health", headers=headers)
            reachable = r.status_code < 500
            b1e55ed_status = "ok" if reachable else f"http {r.status_code}"
    except Exception as exc:
        b1e55ed_status = str(exc)[:120]

    return {
        "gateway": "ok",
        "b1e55ed_reachable": reachable,
        "b1e55ed_status": b1e55ed_status,
        "ts": _utcnow(),
    }


@app.post("/mcp/call")
async def mcp_call(body: MCPRequest, x_api_key: str | None = Header(None)) -> dict:
    """Proxy an MCP ``tools/call`` to b1e55ed with RBAC enforcement."""
    user = _authenticate(x_api_key)
    name = user["name"]
    role = user["role"]

    tool_name: str = body.params.get("name", "")
    tool_args: dict = body.params.get("arguments", {})

    # ---- authorisation ----
    allowed = _allowed_tools(role)
    if tool_name not in allowed:
        _audit(name, role, tool_name, tool_args, "denied")
        return {
            "jsonrpc": "2.0",
            "id": body.id,
            "error": {"code": -32600, "message": f"Role '{role}' cannot call '{tool_name}'"},
        }

    # ---- signal approval workflow ----
    if tool_name == "submit_research_signal" and role != "admin":
        signal_id = str(uuid.uuid4())[:8]
        pending = {
            "signal_id": signal_id,
            "user": name,
            "role": role,
            "tool": tool_name,
            "arguments": tool_args,
            "ts": _utcnow(),
            "status": "pending",
        }
        with open(PENDING_PATH, "a") as f:
            f.write(json.dumps(pending) + "\n")
        _audit(name, role, tool_name, tool_args, "queued", f"signal_id={signal_id}")
        return {
            "jsonrpc": "2.0",
            "id": body.id,
            "result": {"queued": True, "signal_id": signal_id, "message": "Signal queued for admin approval"},
        }

    # ---- proxy to b1e55ed ----
    try:
        result = await _proxy_to_b1e55ed(body)
        _audit(name, role, tool_name, tool_args, "ok")
        return result
    except Exception as exc:
        _audit(name, role, tool_name, tool_args, "error", str(exc)[:200])
        return {
            "jsonrpc": "2.0",
            "id": body.id,
            "error": {"code": -32603, "message": f"Upstream error: {exc!s}"[:200]},
        }


@app.post("/approve/{signal_id}")
async def approve_signal(signal_id: str, x_api_key: str | None = Header(None)) -> dict:
    """Admin-only: approve a pending research signal and forward it upstream."""
    user = _authenticate(x_api_key)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admins can approve signals")

    # Find and mark pending signal
    if not PENDING_PATH.exists():
        raise HTTPException(status_code=404, detail="No pending signals")

    lines = PENDING_PATH.read_text().splitlines()
    found = None
    updated: list[str] = []
    for line in lines:
        entry = json.loads(line)
        if entry.get("signal_id") == signal_id and entry.get("status") == "pending":
            entry["status"] = "approved"
            entry["approved_by"] = user["name"]
            entry["approved_at"] = _utcnow()
            found = entry
        updated.append(json.dumps(entry))
    if not found:
        raise HTTPException(status_code=404, detail=f"Pending signal '{signal_id}' not found")

    PENDING_PATH.write_text("\n".join(updated) + "\n")

    # Forward the original call upstream
    rpc = MCPRequest(
        method="tools/call",
        params={"name": found["tool"], "arguments": found["arguments"]},
        id=f"approved-{signal_id}",
    )
    try:
        result = await _proxy_to_b1e55ed(rpc)
        _audit(user["name"], user["role"], found["tool"], found["arguments"], "approved", f"signal_id={signal_id}")
        return {"approved": True, "signal_id": signal_id, "upstream_result": result}
    except Exception as exc:
        _audit(user["name"], user["role"], found["tool"], found["arguments"], "approve_error", str(exc)[:200])
        raise HTTPException(status_code=502, detail=f"Approved but upstream failed: {exc!s}"[:200]) from exc


@app.get("/pending")
async def list_pending(x_api_key: str | None = Header(None)) -> dict:
    """List pending signals (admin only)."""
    user = _authenticate(x_api_key)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    if not PENDING_PATH.exists():
        return {"pending": []}
    entries = [json.loads(line) for line in PENDING_PATH.read_text().splitlines() if line.strip()]
    return {"pending": [e for e in entries if e.get("status") == "pending"]}


# ---------------------------------------------------------------------------
# Upstream proxy
# ---------------------------------------------------------------------------


async def _proxy_to_b1e55ed(rpc: MCPRequest) -> dict:
    """Forward a JSON-RPC MCP request to the b1e55ed oracle."""
    headers = {"Content-Type": "application/json"}
    if B1E55ED_TOKEN:
        headers["Authorization"] = f"Bearer {B1E55ED_TOKEN}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{B1E55ED_URL}/mcp/call",
            json=rpc.model_dump(),
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=CFG.get("port", 7338))
