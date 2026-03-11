# MCP Integration

b1e55ed exposes MCP over **JSON-RPC 2.0 via HTTP**.

## Endpoint map

| Surface | Endpoint(s) | Purpose |
|---|---|---|
| MCP JSON-RPC | `POST /mcp` (also available at `POST /api/v1/mcp`) | `initialize`, `tools/list`, `tools/call` |
| MCP registry snapshot | `GET /api/v1/mcp/producers`, `GET /api/v1/mcp/status` (also mounted at `/mcp/producers` and `/mcp/status`) | Read in-memory producer manifests + latest buffered signals |
| Event stream (non-MCP) | `GET /api/v1/events/stream` | SSE feed of engine events |

> MCP transport is HTTP JSON-RPC. The MCP endpoint itself is **not SSE**.

## Auth behavior (exact)

### `POST /mcp` (and `POST /api/v1/mcp`)

- `initialize` and `tools/list` are **public** (no auth required).
- `tools/call` requires auth **if** `api.auth_token` is set:
  - `X-API-Key: <api.auth_token>` **or**
  - `Authorization: Bearer <api.auth_token>`
- If `api.auth_token` is empty, all MCP methods are effectively public.

### `GET /api/v1/mcp/producers` and `GET /api/v1/mcp/status`

- Open by default (`mcp.require_auth=false`).
- If `mcp.require_auth=true`, requests must include:
  - `X-MCP-Key: <one of config.mcp.api_keys>`
- Invalid or missing key returns `403 Invalid MCP API key`.

## Quick start (executable)

### 1) Initialize (public)

```bash
curl -s http://localhost:5050/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
```

### 2) List tools (public)

```bash
curl -s http://localhost:5050/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

### 3) Call a tool (auth required when `api.auth_token` is set)

```bash
curl -s http://localhost:5050/mcp \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $TOKEN" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_brain_status","arguments":{}}}'
```

### 4) Read MCP registry status (open unless `mcp.require_auth=true`)

```bash
curl -s http://localhost:5050/api/v1/mcp/status
```

If registry auth is enabled:

```bash
curl -s http://localhost:5050/api/v1/mcp/status \
  -H "X-MCP-Key: $MCP_KEY"
```

## Current MCP tool contract (`tools/list`)

The server currently exposes these tool names:

1. `get_brain_status`
2. `get_recent_signals`
3. `get_open_positions`
4. `get_signal_attribution`
5. `b1e55ed_provenance_check`
6. `emit_producer_signal`
7. `get_regime_status`
8. `get_top_signals`
9. `get_regime_history`
10. `submit_research_signal`
11. `get_signals_bulk_export`

### Tool argument summary

| Tool | Required arguments | Notes |
|---|---|---|
| `get_brain_status` | none | Regime + kill switch + last cycle metadata |
| `get_recent_signals` | none | Optional: `limit` (max 100), `domain` (prefix filter, e.g. `signal.ta`) |
| `get_open_positions` | none | Returns non-closed positions from OMS |
| `get_signal_attribution` | `signal_id` | Returns event attribution details |
| `b1e55ed_provenance_check` | `producer_id` | Optional: `signal_type` |
| `emit_producer_signal` | `producer_id`, `signal_type`, `payload` | `signal_type` must be a registered `signal.*` event type |
| `get_regime_status` | none | Current regime + trend |
| `get_top_signals` | none | Optional: `domain`, `symbol`, `signal_class`, `cursor`, `limit` |
| `get_regime_history` | none | Optional: `days` (max 30) |
| `submit_research_signal` | `symbol`, `signal_class`, `confidence`, `direction`, `rationale`, `operator_node_id` | `conviction` requires `horizon`; `detection` requires `event_ts`; `observation` must be `direction=neutral` |
| `get_signals_bulk_export` | none | Optional: `domain`, `symbol`, `from_ts`, `to_ts`, `cursor`, `limit` (max 1000) |

## MCP registry response shape

`GET /api/v1/mcp/producers` returns:

- `producers`: list of producer manifests
  - `name`, `domain`, `mcp_source_url`, `description`, `assets`, `schedule`, `registered_at`
  - `latest_signal` (or `null`)
- `count`: number of registered producers

`latest_signal` uses this schema:

| Field | Type |
|---|---|
| `producer` | `str` |
| `domain` | `str` |
| `asset` | `str | null` |
| `direction` | `str | null` |
| `confidence` | `float | null` |
| `horizon` | `str | null` |
| `reason` | `str` |
| `timestamp` | `str` |
| `raw_score` | `float | null` |
| `metadata` | `dict` |

## Configuration

```yaml
mcp:
  enabled: true
  port: 7337
  require_auth: false
  api_keys: []
```

- `enabled`: enables MCP-related features.
- `port`: reserved for the optional FastMCP server implementation.
- `require_auth`: gates `/api/v1/mcp/producers` and `/api/v1/mcp/status` with `X-MCP-Key`.
- `api_keys`: allowed values for `X-MCP-Key`.

## Security notes

- Set `api.auth_token` to protect `tools/call` on `/mcp`.
- If exposing registry endpoints publicly, set `mcp.require_auth=true` and configure strong `mcp.api_keys`.
- SSE event streaming is separate (`/api/v1/events/stream`) and uses API auth.

Related docs:
- [agent-interfaces.md](agent-interfaces.md)
- [api-reference.md](api-reference.md)
- [configuration.md](configuration.md)
