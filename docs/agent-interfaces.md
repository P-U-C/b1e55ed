# Agent Interfaces

b1e55ed exposes three real-time interfaces for AI agents:

| Interface | Endpoint | Auth | Use |
|-----------|----------|------|-----|
| SSE stream | `GET /api/v1/events/stream` | Required | Real-time event feed |
| MCP server | `POST /api/v1/mcp` | Required | Tool calls |
| Oracle | `GET /api/v1/oracle/producers/{id}/provenance` | None | Provenance check |

## SSE event stream

```
GET /api/v1/events/stream
Authorization: Bearer <token>
```

Returns a Server-Sent Events stream. Reconnect is safe — use `?since=<event_id>` to resume.

Query params:
- `domain` — filter by event domain (e.g. `signal`, `alert`, `learning`)
- `since` — resume from a specific event ID (inclusive)

Event format:

```
data: {"id":"123","type":"signal.ta.rsi.v1","ts":"2026-02-20T00:00:00Z","source":"producer.ta","payload":{...}}
```

Example (curl):

```bash
curl -N \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:5050/api/v1/events/stream?domain=alert"
```

## MCP server

Standard MCP JSON-RPC 2.0 server.

```
POST /api/v1/mcp
Content-Type: application/json
Authorization: Bearer <token>
```

List available tools:

```json
{"jsonrpc":"2.0","method":"tools/list","id":1,"params":{}}
```

Available tools:

- `get_brain_status` — current regime, kill switch level, last cycle
- `get_recent_signals` — recent signal events with optional domain filter
- `get_open_positions` — open positions with P&L
- `get_signal_attribution` — attribution data for a specific signal
- `emit_producer_signal` — emit a signal event from an agent producer
- `b1e55ed_provenance_check` — check producer lineage before acting on a signal

## Signal attribution

```
GET /api/v1/signals/{signal_id}/attribution
Authorization: Bearer <token>
```

Returns attribution data for a specific signal: contributor, source, outcome if settled.

## Capabilities discovery

```
GET /api/v1/capabilities
Authorization: Bearer <token>
```

Returns what this instance supports — tools, event domains, producer list. Use for agent onboarding.

## Trace sessions

For agents that need stateful interaction tracking:

```
POST /api/v1/trace/sessions          — create session
GET /api/v1/trace/sessions           — list sessions
GET /api/v1/trace/sessions/{id}      — get session state
DELETE /api/v1/trace/sessions/{id}   — close session
```

Sessions are lightweight. They track which agent is interacting, when, and what they've seen.

## Producer feedback

Agents can report signal outcomes back to the engine:

```
POST /api/v1/producers/{id}/feedback
```

This feeds the learning loop.

## Oracle (no auth)

The oracle endpoint requires no authentication and is safe to expose publicly:

```
GET /api/v1/oracle/producers/{producer_id}/provenance
```

See: [oracle.md](oracle.md) for full documentation.
