"""api.routes.mcp

MCP signal registry + JSON-RPC endpoints.

Exposes the MCPProducerRegistry over HTTP so external agents and dashboards
can discover live producer signals without a direct MCP protocol connection.

GET /api/v1/mcp/producers  — list all registered producers + latest signal
GET /api/v1/mcp/status     — registry health and stats

Also serves the JSON-RPC MCP endpoint used by MCP-aware clients:
POST /mcp
"""

from __future__ import annotations

import hmac
import json
import logging
from dataclasses import asdict
from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse

from api.deps import get_config, get_db
from engine.core.config import Config
from engine.core.database import Database
from engine.mcp.auth import get_mcp_auth_dependency
from engine.mcp.registry import get_registry as get_mcp_registry

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mcp"])

# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------

JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2024-11-05"


def _ok(id: Any, result: Any) -> dict:
    return {"jsonrpc": JSONRPC_VERSION, "id": id, "result": result}


def _err(id: Any, code: int, message: str, data: Any = None) -> dict:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": JSONRPC_VERSION, "id": id, "error": err}


# JSON-RPC error codes
_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603

# ---------------------------------------------------------------------------
# Auth helper (X-API-Key or Bearer token)
# ---------------------------------------------------------------------------


def _check_auth(request: Request, x_api_key: str | None) -> bool:
    """Accept X-API-Key header or fall back to bearer token validation."""
    config: Config = get_config(request)
    expected = str(getattr(config.api, "auth_token", "") or "")
    if not expected:
        import logging

        logging.getLogger("b1e55ed.auth.mcp").critical("MCP endpoint has no auth token configured — MCP is PUBLIC.")
        return True

    # Try X-API-Key first
    if x_api_key and hmac.compare_digest(x_api_key.strip(), expected):
        return True

    # Fall back to Authorization: Bearer
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
        if hmac.compare_digest(token, expected):
            return True

    return False


def _require_mcp_registry_auth(
    request: Request,
    x_mcp_key: str | None = Header(default=None, alias="X-MCP-Key"),
) -> None:
    """Optional API-key gate for /api/v1/mcp/* registry endpoints."""

    config: Config = get_config(request)
    auth_dependency = get_mcp_auth_dependency(config)
    auth_dependency(x_mcp_key)


@router.get("/mcp/producers", dependencies=[Depends(_require_mcp_registry_auth)])
def list_mcp_producers() -> dict:
    """List all producers with their manifest and latest signal (if available)."""

    registry = get_mcp_registry()
    producers: list[dict[str, Any]] = []

    for manifest in registry.list_producers():
        latest_signal = registry.get_latest(manifest.name)
        manifest_payload = asdict(manifest)
        manifest_payload["latest_signal"] = asdict(latest_signal) if latest_signal is not None else None
        producers.append(manifest_payload)

    return {
        "producers": producers,
        "count": len(producers),
    }


@router.get("/mcp/status", dependencies=[Depends(_require_mcp_registry_auth)])
def mcp_status(request: Request) -> dict:
    """Return MCP registry availability and buffer stats."""

    registry = get_mcp_registry()
    stats = registry.stats()
    config: Config = get_config(request)

    return {
        "enabled": bool(config.mcp.enabled),
        "producer_count": int(stats.get("producer_count", 0)),
        "total_signals_buffered": int(stats.get("total_signals_buffered", 0)),
        "registry_ok": True,
    }


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_brain_status",
        "description": "Returns the current brain status including regime, kill-switch level, and last cycle info.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_recent_signals",
        "description": "Returns recent brain signals from the event store.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of signals to return (default 20, max 100)",
                    "default": 20,
                },
                "domain": {
                    "type": "string",
                    "description": "Filter by domain prefix e.g. 'signal.ta', 'signal.onchain'",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_open_positions",
        "description": "Returns all currently open positions from the OMS.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_signal_attribution",
        "description": "Returns attribution metadata for a specific signal (event) by its ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "signal_id": {
                    "type": "string",
                    "description": "The event ID of the signal to look up",
                },
            },
            "required": ["signal_id"],
        },
    },
    {
        "name": "b1e55ed_provenance_check",
        "description": (
            "Check signal producer lineage before executing a trade. "
            "Returns chain-verified history and coverage data. "
            "Does NOT return a trust score or recommendation — the agent decides what the data means."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "producer_id": {
                    "type": "string",
                    "description": "The signal producer or source identifier to check",
                },
                "signal_type": {
                    "type": "string",
                    "description": "Optional signal type filter (e.g. 'long_btc', 'short_eth')",
                },
            },
            "required": ["producer_id"],
        },
    },
    {
        "name": "emit_producer_signal",
        "description": "Injects a signal into the ingestion bus on behalf of a registered producer.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "producer_id": {
                    "type": "string",
                    "description": "Name/ID of the registered producer",
                },
                "signal_type": {
                    "type": "string",
                    "description": "Event type e.g. 'signal.ta.v1'",
                },
                "payload": {
                    "type": "object",
                    "description": "Signal payload dict",
                },
            },
            "required": ["producer_id", "signal_type", "payload"],
        },
    },
    {
        "name": "get_regime_status",
        "description": "Returns current regime, kill switch level, and last cycle timestamp with trend indicator.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_top_signals",
        "description": "Returns recent signals with optional domain/symbol/signal_class filter and cursor-based pagination.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Filter by domain prefix (e.g. 'onchain', 'ta', 'research')"},
                "symbol": {"type": "string", "description": "Filter by symbol in payload"},
                "limit": {"type": "integer", "description": "Max results (default 20, max 100)", "default": 20},
                "cursor": {"type": "string", "description": "Event ID to paginate from (exclusive)"},
                "signal_class": {"type": "string", "description": "Filter by signal_class field in payload"},
            },
            "required": [],
        },
    },
    {
        "name": "get_regime_history",
        "description": "Returns regime change history for the last N days with stability indicator.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Number of days of history (default 7, max 30)", "default": 7},
            },
            "required": [],
        },
    },
    {
        "name": "submit_research_signal",
        "description": "Validates and emits a signal.research.v1 event from a DeerFlow research task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Trading symbol (e.g. 'BTC')"},
                "signal_class": {"type": "string", "enum": ["observation", "detection", "conviction"]},
                "confidence": {"type": "number", "description": "Confidence (0.0-1.0)"},
                "direction": {"type": "string", "description": "'bullish', 'bearish', or 'neutral'"},
                "rationale": {"type": "string", "description": "Reasoning behind the signal"},
                "operator_node_id": {"type": "string", "description": "Forge node ID of the human operator"},
                "horizon": {"type": "string", "description": "REQUIRED for conviction signals (e.g. '1-7d')"},
                "sources": {"type": "array", "items": {"type": "string"}},
                "deerflow_task_id": {"type": "string"},
                "artifact_url": {"type": "string"},
            },
            "required": ["symbol", "signal_class", "confidence", "direction", "rationale", "operator_node_id"],
        },
    },
    {
        "name": "get_signals_bulk_export",
        "description": "Bulk export of historical signals for backtest use (up to 1000 per call).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Filter by domain prefix"},
                "symbol": {"type": "string", "description": "Filter by symbol in payload"},
                "from_ts": {"type": "string", "description": "ISO timestamp start"},
                "to_ts": {"type": "string", "description": "ISO timestamp end"},
                "cursor": {"type": "string", "description": "Pagination cursor (event ID)"},
                "limit": {"type": "integer", "description": "Max results (default 200, max 1000)", "default": 200},
            },
            "required": [],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


def _tool_get_brain_status(db: Database, params: dict) -> dict:
    regime = None
    regime_at = None
    row = db.conn.execute(
        "SELECT payload, ts FROM events WHERE type = ? ORDER BY ts DESC LIMIT 1",
        ("brain.regime_change.v1",),
    ).fetchone()
    if row is not None:
        p = json.loads(str(row[0]))
        regime = p.get("regime") or p.get("state") or p.get("name")
        regime_at = str(row[1])

    ks_level = 0
    ks_reason = None
    ks_row = db.conn.execute(
        "SELECT payload FROM events WHERE type = ? ORDER BY ts DESC LIMIT 1",
        ("system.kill_switch.v1",),
    ).fetchone()
    if ks_row is not None:
        p = json.loads(str(ks_row[0]))
        ks_level = int(p.get("level", 0))
        ks_reason = p.get("reason")

    last_cycle_id = None
    last_cycle_at = None
    cy_row = db.conn.execute(
        "SELECT payload, ts FROM events WHERE type = ? ORDER BY ts DESC LIMIT 1",
        ("brain.cycle.v1",),
    ).fetchone()
    if cy_row is not None:
        p = json.loads(str(cy_row[0]))
        last_cycle_id = p.get("cycle_id")
        last_cycle_at = str(cy_row[1])

    return {
        "regime": regime,
        "regime_changed_at": regime_at,
        "kill_switch_level": ks_level,
        "kill_switch_reason": ks_reason,
        "last_cycle_id": last_cycle_id,
        "last_cycle_at": last_cycle_at,
    }


def _tool_get_recent_signals(db: Database, params: dict) -> list[dict]:
    limit = min(int(params.get("limit", 20)), 100)
    domain: str | None = params.get("domain")

    if domain:
        # Match on the type prefix
        pattern = f"{domain}%"
        rows = db.conn.execute(
            "SELECT id, type, ts, source, payload FROM events WHERE type LIKE ? ORDER BY ts DESC LIMIT ?",
            (pattern, limit),
        ).fetchall()
    else:
        rows = db.conn.execute(
            "SELECT id, type, ts, source, payload FROM events WHERE type LIKE 'signal.%' ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()

    result = []
    for r in rows:
        result.append(
            {
                "id": str(r[0]),
                "type": str(r[1]),
                "ts": str(r[2]),
                "source": str(r[3]) if r[3] is not None else None,
                "payload": json.loads(str(r[4])),
            }
        )
    return result


def _tool_get_open_positions(db: Database, params: dict) -> list[dict]:
    rows = db.conn.execute(
        """
        SELECT id, platform, asset, direction, entry_price, size_notional, leverage,
               stop_loss, take_profit, opened_at, status, realized_pnl
        FROM positions
        WHERE status NOT IN ('closed', 'liquidated')
        ORDER BY opened_at DESC
        """,
    ).fetchall()

    result = []
    for r in rows:
        result.append(
            {
                "id": str(r[0]),
                "platform": str(r[1]),
                "asset": str(r[2]),
                "direction": str(r[3]),
                "entry_price": float(r[4]),
                "size_notional": float(r[5]),
                "leverage": float(r[6]) if r[6] is not None else None,
                "stop_loss": float(r[7]) if r[7] is not None else None,
                "take_profit": float(r[8]) if r[8] is not None else None,
                "opened_at": str(r[9]),
                "status": str(r[10]),
                "realized_pnl": float(r[11]) if r[11] is not None else None,
            }
        )
    return result


def _tool_get_signal_attribution(db: Database, params: dict) -> dict:
    signal_id = params.get("signal_id")
    if not signal_id:
        raise ValueError("signal_id is required")

    row = db.conn.execute(
        "SELECT id, type, ts, source, contributor_id, trace_id, payload FROM events WHERE id = ?",
        (signal_id,),
    ).fetchone()
    if row is None:
        return {"error": "signal_not_found", "signal_id": signal_id}

    payload = json.loads(str(row[6]))
    result: dict[str, Any] = {
        "signal_id": str(row[0]),
        "type": str(row[1]),
        "ts": str(row[2]),
        "source": str(row[3]) if row[3] is not None else None,
        "contributor_id": str(row[4]) if row[4] is not None else None,
        "trace_id": str(row[5]) if row[5] is not None else None,
        "payload": payload,
    }

    # Attribution: look up contributor info if available
    if row[4]:
        contrib_row = db.conn.execute(
            "SELECT node_id, name, role FROM contributors WHERE id = ?",
            (row[4],),
        ).fetchone()
        if contrib_row is not None:
            result["contributor"] = {
                "node_id": str(contrib_row[0]),
                "name": str(contrib_row[1]),
                "role": str(contrib_row[2]),
            }

    return result


def _tool_provenance_check(db: Database, params: dict) -> dict:
    """MCP handler for b1e55ed_provenance_check.

    Delegates to the shared provenance logic in engine.core.provenance so
    the REST endpoint and the MCP tool always return the same data.
    """
    from engine.core.provenance import compute_provenance

    producer_id = params.get("producer_id")
    if not producer_id:
        raise ValueError("producer_id is required")

    result = compute_provenance(str(producer_id), db)

    out: dict = {
        "producer_id": result.producer_id,
        "has_provenance": result.has_provenance,
        "chain_verified": result.chain_verified,
        "total_signals": result.total_signals,
        "p_and_l_attributed": result.p_and_l_attributed,
        "operator_coverage": result.operator_coverage,
        "first_seen": result.first_seen,
        "last_seen": result.last_seen,
        "note": result.note,
        "attribution_windows": {
            k: {
                "signals": v.signals,
                "hit_rate": v.hit_rate,
                "max_drawdown_pct": v.max_drawdown_pct,
            }
            for k, v in result.attribution_windows.items()
        },
    }
    return out


def _tool_emit_producer_signal(db: Database, params: dict) -> dict:
    producer_id = params.get("producer_id")
    signal_type = params.get("signal_type")
    payload = params.get("payload", {})

    if not producer_id:
        raise ValueError("producer_id is required")
    if not signal_type:
        raise ValueError("signal_type is required")
    if not str(signal_type).startswith("signal."):
        raise ValueError("signal_type must start with 'signal.'")

    emitted_at = datetime.now(tz=UTC).isoformat()

    from engine.core.events import EventType as _EventType

    try:
        etype = _EventType(signal_type)
    except ValueError as exc:
        raise ValueError(f"Unknown signal_type: {signal_type!r}. Must be a registered EventType.") from exc

    event = db.append_event(
        event_type=etype,
        payload=payload,
        source=f"mcp.producer.{producer_id}",
        ts=datetime.now(tz=UTC),
    )

    return {
        "event_id": event.id,
        "producer_id": producer_id,
        "signal_type": signal_type,
        "emitted_at": emitted_at,
    }


# ---------------------------------------------------------------------------
# DeerFlow S0 tools
# ---------------------------------------------------------------------------


def _tool_get_regime_status(db: Database, params: dict) -> dict:
    """Returns current regime, kill switch level, last cycle timestamp, and trend."""
    regime = None
    regime_at = None
    trend = "stable"

    rows = db.conn.execute(
        "SELECT payload, ts FROM events WHERE type = ? ORDER BY ts DESC LIMIT 2",
        ("brain.regime_change.v1",),
    ).fetchall()

    if rows:
        p = json.loads(str(rows[0][0]))
        regime = p.get("regime") or p.get("state") or p.get("name")
        regime_at = str(rows[0][1])
        if len(rows) == 2:
            prev_p = json.loads(str(rows[1][0]))
            prev_regime = prev_p.get("regime") or prev_p.get("state") or prev_p.get("name")
            if regime == prev_regime:
                trend = "stable"
            elif regime == "bull":
                trend = "strengthening"
            elif regime == "bear":
                trend = "weakening"
            else:
                trend = "stable"

    ks_level = 0
    ks_reason = None
    ks_row = db.conn.execute(
        "SELECT payload FROM events WHERE type = ? ORDER BY ts DESC LIMIT 1",
        ("system.kill_switch.v1",),
    ).fetchone()
    if ks_row is not None:
        p = json.loads(str(ks_row[0]))
        ks_level = int(p.get("level", 0))
        ks_reason = p.get("reason")

    last_cycle_at = None
    cy_row = db.conn.execute(
        "SELECT ts FROM events WHERE type = ? ORDER BY ts DESC LIMIT 1",
        ("brain.cycle.v1",),
    ).fetchone()
    if cy_row is not None:
        last_cycle_at = str(cy_row[0])

    return {
        "regime": regime,
        "regime_changed_at": regime_at,
        "kill_switch_level": ks_level,
        "kill_switch_reason": ks_reason,
        "last_cycle_at": last_cycle_at,
        "trend": trend,
    }


def _tool_get_top_signals(db: Database, params: dict) -> dict:
    """Recent signals with optional filters and cursor pagination."""
    limit = min(int(params.get("limit", 20)), 100)
    domain: str | None = params.get("domain")
    symbol: str | None = params.get("symbol")
    cursor: str | None = params.get("cursor")
    signal_class: str | None = params.get("signal_class")

    conditions = ["type LIKE 'signal.%'"]
    args: list[Any] = []

    if domain:
        conditions.append("type LIKE ?")
        args.append(f"signal.{domain}%")
    if symbol:
        conditions.append("json_extract(payload, '$.symbol') = ?")
        args.append(symbol)
    if signal_class:
        conditions.append("json_extract(payload, '$.signal_class') = ?")
        args.append(signal_class)
    if cursor:
        cursor_row = db.conn.execute("SELECT ts FROM events WHERE id = ?", (cursor,)).fetchone()
        if cursor_row:
            conditions.append("(ts < ? OR (ts = ? AND id < ?))")
            args.extend([str(cursor_row[0]), str(cursor_row[0]), cursor])

    where = " AND ".join(conditions)
    query = f"SELECT id, type, ts, source, payload FROM events WHERE {where} ORDER BY ts DESC, id DESC LIMIT ?"
    args.append(limit)
    rows = db.conn.execute(query, tuple(args)).fetchall()

    items = []
    for r in rows:
        payload = json.loads(str(r[4]))
        item: dict[str, Any] = {
            "id": str(r[0]),
            "type": str(r[1]),
            "ts": str(r[2]),
            "source": str(r[3]) if r[3] is not None else None,
            "payload": payload,
        }
        if "signal_class" in payload:
            item["signal_class"] = payload["signal_class"]
        items.append(item)

    return {
        "items": items,
        "next_cursor": items[-1]["id"] if len(items) == limit else None,
        "total_returned": len(items),
    }


def _tool_get_regime_history(db: Database, params: dict) -> dict:
    """Regime change history for last N days with stability indicator."""
    days = min(int(params.get("days", 7)), 30)
    rows = db.conn.execute(
        "SELECT payload, ts FROM events WHERE type = ? AND ts > datetime('now', ?) ORDER BY ts DESC",
        ("brain.regime_change.v1", f"-{days} days"),
    ).fetchall()

    items = []
    for i, row in enumerate(rows):
        p = json.loads(str(row[0]))
        regime = p.get("regime") or p.get("state") or p.get("name")
        changed_at = str(row[1])
        duration_hours = None
        if i > 0:
            try:
                dt_current = datetime.fromisoformat(str(changed_at).replace("Z", "+00:00"))
                dt_next = datetime.fromisoformat(str(rows[i - 1][1]).replace("Z", "+00:00"))
                duration_hours = round((dt_next - dt_current).total_seconds() / 3600, 1)
            except (ValueError, TypeError):
                pass
        items.append({"regime": regime, "changed_at": changed_at, "duration_hours": duration_hours})

    return {
        "items": items,
        "current_regime": items[0]["regime"] if items else None,
        "regime_stability": "volatile" if len(items) > 3 else "stable",
    }


# Popper (1934): a claim that cannot be falsified is not science.
# operator_node_id is the signature. horizon is the falsification window.
# Without both, a research signal is opinion dressed as evidence.
def _tool_submit_research_signal(db: Database, params: dict) -> dict:
    """Validate and emit a signal.research.v1 event."""
    from engine.core.events import EventType as _EventType
    from engine.core.events import ResearchSignalPayload
    from engine.core.karma import ensure_producer_karma_config

    required = ["symbol", "signal_class", "confidence", "direction", "rationale", "operator_node_id"]
    missing = [f for f in required if not params.get(f)]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")

    operator_node_id = str(params["operator_node_id"]).strip()
    if not operator_node_id:
        raise ValueError("operator_node_id must be a non-empty string")

    payload_data: dict[str, Any] = {
        "symbol": params["symbol"],
        "signal_class": params["signal_class"],
        "confidence": float(params["confidence"]),
        "direction": params["direction"],
        "rationale": params["rationale"],
        "operator_node_id": operator_node_id,
    }
    for opt in ("horizon", "deerflow_task_id", "artifact_url"):
        if params.get(opt):
            payload_data[opt] = params[opt]
    if params.get("sources"):
        payload_data["sources"] = params["sources"]

    validated = ResearchSignalPayload(**payload_data)
    source = f"deerflow:{operator_node_id}"
    ensure_producer_karma_config(db, source, source_type="llm_research")

    ceiling_row = db.conn.execute(
        "SELECT karma_ceiling FROM producer_karma_config WHERE producer_name = ?",
        (source,),
    ).fetchone()
    karma_ceiling_active = ceiling_row is not None and float(ceiling_row[0]) < 1.0

    event = db.append_event(
        event_type=_EventType.SIGNAL_RESEARCH_V1,
        payload=validated.model_dump(mode="json"),
        source=source,
        contributor_id=operator_node_id,
        ts=datetime.now(tz=UTC),
    )
    return {"event_id": event.id, "signal_class": str(validated.signal_class), "karma_ceiling_active": karma_ceiling_active}


def _tool_get_signals_bulk_export(db: Database, params: dict) -> dict:
    """Bulk export of historical signals for backtest use."""
    limit = min(int(params.get("limit", 200)), 1000)
    domain: str | None = params.get("domain")
    symbol: str | None = params.get("symbol")
    from_ts: str | None = params.get("from_ts")
    to_ts: str | None = params.get("to_ts")
    cursor: str | None = params.get("cursor")

    conditions = ["type LIKE 'signal.%'"]
    args: list[Any] = []
    if domain:
        conditions.append("type LIKE ?")
        args.append(f"signal.{domain}%")
    if symbol:
        conditions.append("json_extract(payload, '$.symbol') = ?")
        args.append(symbol)
    if from_ts:
        conditions.append("ts >= ?")
        args.append(from_ts)
    if to_ts:
        conditions.append("ts <= ?")
        args.append(to_ts)
    if cursor:
        cursor_row = db.conn.execute("SELECT ts FROM events WHERE id = ?", (cursor,)).fetchone()
        if cursor_row:
            conditions.append("(ts < ? OR (ts = ? AND id < ?))")
            args.extend([str(cursor_row[0]), str(cursor_row[0]), cursor])

    where = " AND ".join(conditions)
    query = f"SELECT id, type, ts, source, payload FROM events WHERE {where} ORDER BY ts DESC, id DESC LIMIT ?"
    args.append(limit)
    rows = db.conn.execute(query, tuple(args)).fetchall()

    items = []
    for r in rows:
        payload = json.loads(str(r[4]))
        item: dict[str, Any] = {
            "id": str(r[0]),
            "type": str(r[1]),
            "ts": str(r[2]),
            "source": str(r[3]) if r[3] is not None else None,
            "payload": payload,
        }
        if "signal_class" in payload:
            item["signal_class"] = payload["signal_class"]
        items.append(item)

    return {
        "items": items,
        "next_cursor": items[-1]["id"] if len(items) == limit else None,
        "total_returned": len(items),
    }


# Map tool names to their handlers
_TOOL_HANDLERS = {
    "get_brain_status": _tool_get_brain_status,
    "get_recent_signals": _tool_get_recent_signals,
    "get_open_positions": _tool_get_open_positions,
    "get_signal_attribution": _tool_get_signal_attribution,
    "b1e55ed_provenance_check": _tool_provenance_check,
    "emit_producer_signal": _tool_emit_producer_signal,
    "get_regime_status": _tool_get_regime_status,
    "get_top_signals": _tool_get_top_signals,
    "get_regime_history": _tool_get_regime_history,
    "submit_research_signal": _tool_submit_research_signal,
    "get_signals_bulk_export": _tool_get_signals_bulk_export,
}


# ---------------------------------------------------------------------------
# MCP endpoint
# ---------------------------------------------------------------------------


@router.post("/mcp")
async def mcp_endpoint(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> JSONResponse:
    """JSON-RPC 2.0 MCP server endpoint."""

    # Auth check
    if not _check_auth(request, x_api_key):
        return JSONResponse(
            status_code=401,
            content=_err(None, -32001, "Unauthorized: provide X-API-Key or Authorization: Bearer header"),
        )

    # Parse body
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content=_err(None, _PARSE_ERROR, "Parse error: invalid JSON"),
        )

    if not isinstance(body, dict):
        return JSONResponse(
            status_code=400,
            content=_err(None, _INVALID_REQUEST, "Invalid request: body must be a JSON object"),
        )

    rpc_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}

    if body.get("jsonrpc") != JSONRPC_VERSION:
        return JSONResponse(
            status_code=400,
            content=_err(rpc_id, _INVALID_REQUEST, "Invalid request: jsonrpc must be '2.0'"),
        )

    if not method:
        return JSONResponse(
            status_code=400,
            content=_err(rpc_id, _INVALID_REQUEST, "Invalid request: method is required"),
        )

    db: Database = get_db(request)

    # ---------------------------------------------------------------------------
    # Method dispatch
    # ---------------------------------------------------------------------------

    if method == "initialize":
        return JSONResponse(
            content=_ok(
                rpc_id,
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "b1e55ed", "version": "1.0.0"},
                },
            )
        )

    elif method == "tools/list":
        return JSONResponse(content=_ok(rpc_id, {"tools": TOOLS}))

    elif method == "tools/call":
        tool_name = params.get("name") if isinstance(params, dict) else None
        tool_params = params.get("arguments") or params.get("params") or {}
        if isinstance(params, dict) and "name" not in params:
            # Some clients pass positional-style: params = {"name": ..., ...}
            tool_name = params.get("name")

        if not tool_name:
            return JSONResponse(content=_err(rpc_id, _INVALID_PARAMS, "tools/call requires params.name"))

        handler = _TOOL_HANDLERS.get(tool_name)
        if handler is None:
            return JSONResponse(content=_err(rpc_id, _METHOD_NOT_FOUND, f"Unknown tool: {tool_name}"))

        try:
            result = handler(db, tool_params)
        except ValueError as exc:
            return JSONResponse(content=_err(rpc_id, _INVALID_PARAMS, str(exc)))
        except Exception as exc:
            logger.exception("MCP tool %s failed", tool_name)
            return JSONResponse(content=_err(rpc_id, _INTERNAL_ERROR, f"Tool execution error: {exc}"))

        return JSONResponse(
            content=_ok(
                rpc_id,
                {
                    "content": [{"type": "text", "text": json.dumps(result, default=str)}],
                    "isError": False,
                },
            )
        )

    else:
        return JSONResponse(content=_err(rpc_id, _METHOD_NOT_FOUND, f"Method not found: {method}"))
