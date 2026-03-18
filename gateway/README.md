# b1e55ed MCP Gateway

Harness-agnostic FastAPI proxy between any MCP client (DeerFlow, Claude Desktop,
custom agents) and the b1e55ed oracle's `/mcp/call` endpoint.

## Features

- **Per-user API keys** with role-based access control
- **Signal approval workflow** — non-admin `submit_research_signal` calls queue
  for admin review instead of forwarding directly
- **Audit log** — every request logged to `data/audit.jsonl`
- **Health probe** — `GET /health` checks gateway + b1e55ed reachability

## Quick Start

```bash
cd gateway
pip install -r requirements.txt
# Edit config.yaml — set b1e55ed_url + generate real API keys
uvicorn gateway.main:app --host 0.0.0.0 --port 7338
```

## Configuration (`config.yaml`)

| Field | Description |
|-------|-------------|
| `b1e55ed_url` | URL of the b1e55ed oracle (default `http://localhost:5050`) |
| `b1e55ed_token` | Optional bearer token for upstream auth |
| `port` | Gateway listen port (default `7338`) |
| `users` | List of `{api_key, name, role}` entries |

## Roles

| Role | Tools |
|------|-------|
| `analyst` | `get_regime_status`, `get_top_signals`, `get_regime_history`, `get_signals_bulk_export`, `get_brain_status`, `get_recent_signals` |
| `pm` | Analyst tools + `get_open_positions`, `get_signal_attribution` |
| `risk` | PM tools + `b1e55ed_provenance_check` |
| `admin` | All tools including `submit_research_signal`, `emit_producer_signal` |

## Signal Approval Workflow

When a non-admin user calls `submit_research_signal`, the gateway:

1. Queues the signal to `data/pending_signals.jsonl` with a `signal_id`
2. Returns `{"queued": true, "signal_id": "..."}` to the caller
3. Admin reviews via `GET /pending` (with admin API key)
4. Admin approves via `POST /approve/{signal_id}` — gateway forwards upstream

## Auth

Pass `X-API-Key` header with every request.

## Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | None | Gateway + upstream health |
| `POST` | `/mcp/call` | API key | Proxied MCP tool call |
| `GET` | `/pending` | Admin | List pending signals |
| `POST` | `/approve/{signal_id}` | Admin | Approve and forward a queued signal |

## Pointing DeerFlow at the Gateway

See `integrations/deerflow/extensions_config.json` for the gateway mode
configuration, or `docs/deerflow.md` for a full walkthrough.
