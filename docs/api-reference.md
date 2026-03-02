# API Reference

REST API for b1e55ed.

## Base URL

```text
http://localhost:5050/api/v1/
```

## Authentication

All endpoints except `GET /health` and `GET /oracle/producers/{id}/provenance` require a bearer token.

b1e55ed refuses to start if `api.auth_token` is empty unless `B1E55ED_INSECURE_OK=1` is set.

### Configure the token

```yaml
# config/user.yaml
api:
  auth_token: "your-secret-token"
```

Or via environment variable:

```bash
export B1E55ED_API__AUTH_TOKEN="your-secret-token"
```

### Use the token

```bash
curl \
  -H "Authorization: Bearer your-secret-token" \
  http://localhost:5050/api/v1/brain/status
```

## Error format

```json
{
  "error": {
    "code": "...",
    "message": "..."
  }
}
```

`code` values are stable identifiers intended for automation. Some endpoints may also return FastAPI `HTTPException` errors using `{"detail": "..."}`.

---

## Health

### GET `/health`

Liveness endpoint. No authentication required.

**Response** (`200`):
```json
{
  "version": "1.0.0-beta.4",
  "uptime_seconds": 12.34,
  "db_size_bytes": 123456
}
```

---

## Brain

### GET `/brain/status`

Current brain state derived from events.

**Response** (`200`):
```json
{
  "regime": "EARLY_BULL",
  "regime_changed_at": "2026-02-20T00:00:00+00:00",
  "kill_switch_level": 0,
  "kill_switch_reason": null,
  "kill_switch_changed_at": null,
  "last_cycle_id": "0b6dd0d9-2a21-4d3c-9fd0-7d7f7f6a7d50",
  "last_cycle_at": "2026-02-20T00:30:00+00:00"
}
```

**Errors**: `401` `auth.*`

### POST `/brain/run`

Runs one brain cycle synchronously. Blocked when kill switch level > 0.

**Response** (`200`):
```json
{
  "cycle_id": "0b6dd0d9-2a21-4d3c-9fd0-7d7f7f6a7d50",
  "ts": "2026-02-20T00:30:00+00:00",
  "intents": [],
  "regime": "EARLY_BULL",
  "kill_switch_level": 0
}
```

**Errors**: `401` `auth.*`, `423` `kill_switch.active` (includes `level`)

---

## Signals

### GET `/signals`

Lists recent signal events.

**Query params**:
- `domain` (optional): filter by `signal.<domain>.*`
- `limit` (default 100, max 500)
- `offset` (default 0)

**Response** (`200`):
```json
{
  "items": [
    {
      "id": "1",
      "type": "signal.ta.rsi.v1",
      "ts": "2026-02-20T00:29:58+00:00",
      "source": "producer.ta",
      "payload": {"symbol": "BTC", "rsi_14": 52.1}
    }
  ],
  "limit": 100,
  "offset": 0,
  "total": 1
}
```

**Errors**: `401` `auth.*`

### POST `/signals/submit`

Submit a curator signal with contributor attribution.

Resolves contributor by `node_id`. Records attribution in `contributor_signals`.

**Request**:
```json
{
  "event_type": "signal.curator.v1",
  "ts": "2026-02-20T00:29:58Z",
  "node_id": "b1e55ed-deadbeef",
  "source": "operator:telegram",
  "payload": {
    "symbol": "BTC",
    "direction": "bullish",
    "conviction": 7.0,
    "rationale": "context"
  }
}
```

**Response** (`200`):
```json
{"event_id": "123", "contributor_id": "contrib_abc123"}
```

**Errors**: `400` `signal.invalid_type`, `404` `contributor.not_found`, `401` `auth.*`

### GET `/signals/{signal_id}/attribution`

Attribution data for a specific signal: contributor, source, outcome if settled.

**Errors**: `401` `auth.*`, `404` (signal not found)

---

## Events / SSE

### GET `/events/stream`

Server-Sent Events stream. Reconnect is safe.

**Query params**:
- `domain` — filter by event domain (e.g. `signal`, `alert`, `learning`)
- `since` — resume from a specific event ID (inclusive)

**Auth**: Required (Bearer token)

**Event format**:
```
data: {"id":"123","type":"signal.ta.rsi.v1","ts":"2026-02-20T00:00:00Z","source":"producer.ta","payload":{...}}
```

**Example**:
```bash
curl -N \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:5050/api/v1/events/stream?domain=alert"
```

See: [agent-interfaces.md](agent-interfaces.md).

---

## Positions

### GET `/positions`

Lists open positions.

**Response** (`200`):
```json
[
  {
    "id": "pos_123",
    "platform": "paper",
    "asset": "BTC",
    "direction": "long",
    "entry_price": 95000.0,
    "size_notional": 1000.0,
    "leverage": 2.0,
    "margin_type": "isolated",
    "stop_loss": 93000.0,
    "take_profit": 98000.0,
    "opened_at": "2026-02-20T00:00:00+00:00",
    "closed_at": null,
    "status": "open",
    "realized_pnl": null,
    "conviction_id": 42,
    "regime_at_entry": "EARLY_BULL",
    "pcs_at_entry": 0.72,
    "cts_at_entry": 0.12
  }
]
```

### GET `/positions/{position_id}`

Single position.

**Errors**: `404` `{"detail":"Position not found"}`, `401` `auth.*`

---

## Producers

### GET `/producers/status`

Health and last run metadata for known producers.

### GET `/producers/`

Lists registered producers (database-backed).

### POST `/producers/register`

Registers a producer record.

**Request**:
```json
{
  "name": "example",
  "domain": "onchain",
  "endpoint": "https://example.internal/poll",
  "schedule": "*/15 * * * *"
}
```

**Errors**: `409` `producer.duplicate`

### DELETE `/producers/{name}`

Deregisters a producer.

**Errors**: `404` `producer.not_found`

### POST `/producers/{id}/feedback`

Submit signal outcome feedback from an agent. Feeds the learning loop.

**Errors**: `401` `auth.*`, `404` (producer not found)

---

## Contributors

See also: [contributors.md](contributors.md).

### GET `/contributors/`

Lists contributors.

### POST `/contributors/register`

Registers a contributor.

**Request**:
```json
{
  "node_id": "b1e55ed-deadbeef",
  "name": "local-operator",
  "role": "operator",
  "metadata": {}
}
```

**Errors**: `409` `contributor.duplicate`

### GET `/contributors/{id}`

Returns a contributor.

**Errors**: `404` `contributor.not_found`

### DELETE `/contributors/{id}`

Removes a contributor.

**Errors**: `404` `contributor.not_found`

### GET `/contributors/{id}/score`

Computes contributor score from attribution tables.

**Errors**: `404` `contributor.not_found`

### GET `/contributors/leaderboard`

Top contributors.

**Query params**: `limit` (default 20)

### GET `/contributors/attestations`

Lists contributors with an EAS UID in metadata.

### GET `/contributors/{id}/attestation`

Returns the stored off-chain EAS attestation for a contributor.

**Errors**: `404` `contributor.attestation_not_found|contributor.not_found`

---

## Karma / Treasury

### GET `/treasury`

Karma state from config and DB.

**Response** (`200`):
```json
{
  "enabled": true,
  "percentage": 0.005,
  "treasury_address": "0x...",
  "pending_intents": 0,
  "receipts": 0
}
```

### GET `/karma/intents`

Lists pending karma intents.

### POST `/karma/settle`

Records settlement for a set of intents.

**Request**:
```json
{"intent_ids": ["1", "2"], "tx_hash": "0xabc..."}
```

### GET `/karma/receipts`

Lists settlement receipts.

---

## Cockpit

### GET `/cockpit`

Cockpit dashboard — 4-quadrant "what do I trade today" view. Returns HTML with HTMX 30-second auto-refresh. No authentication required.

### GET `/cockpit/state`

JSON state backing the cockpit dashboard.

**Response** (`200`):
```json
{
  "top_convictions": [],
  "regime": "EARLY_BULL",
  "kill_switch_level": 0,
  "recent_pnl_usd": 142.50,
  "open_positions": []
}
```

---

## Signal Validation

### POST `/signals/validate`

Validate a signal payload against the signal contract schema without persisting it.

**Request body**: Same as `POST /signals/submit`.

**Response** (`200`):
```json
{
  "valid": true,
  "errors": []
}
```

---

## Benchmarks

### POST `/benchmarks/discretionary`

Submit a discretionary signal (human operator override).

**Request body**:
```json
{
  "symbol": "BTC",
  "direction": "bullish",
  "confidence": 0.8,
  "rationale": "Breakout above 70k resistance"
}
```

**Response** (`201`):
```json
{
  "signal_id": "...",
  "accepted": true
}
```

---

## Regime

### GET `/regime`

Current regime and last change timestamp.

**Response** (`200`):
```json
{
  "regime": "EARLY_BULL",
  "changed_at": "2026-02-20T00:00:00+00:00",
  "conditions": {}
}
```

---

## Config

### GET `/config`

Current in-memory configuration.

### POST `/config/validate`

Validates a config payload (does not persist).

### POST `/config`

Validates and writes `config/user.yaml`, updates the in-process config.

---

## Agent

### POST `/mcp`

MCP JSON-RPC 2.0 server. See: [agent-interfaces.md](agent-interfaces.md).

**Auth**: Required

List tools:
```json
{"jsonrpc":"2.0","method":"tools/list","id":1,"params":{}}
```

Available tools: `get_brain_status`, `get_recent_signals`, `get_open_positions`, `get_signal_attribution`, `emit_producer_signal`, `b1e55ed_provenance_check`

### GET `/capabilities`

Returns supported tools, event domains, and producer list. Use for agent onboarding.

**Auth**: Required

### POST `/trace/sessions`

Create a trace session for stateful agent interaction tracking.

### GET `/trace/sessions`

List trace sessions.

### GET `/trace/sessions/{id}`

Get session state.

### DELETE `/trace/sessions/{id}`

Close a trace session.

---

## Oracle

### GET `/oracle/producers/{producer_id}/provenance`

Producer provenance data. **No authentication required.**

Every response includes:
```
X-Attribution-Notice: Fields informational only. May change without notice. Optimizing against specific metrics triggers drift detection.
```

**Response** (`200`, producer with history):
```json
{
  "producer_id": "alpha_signals_v2",
  "has_provenance": true,
  "chain_verified": true,
  "total_signals": 142,
  "p_and_l_attributed": true,
  "operator_coverage": 3,
  "first_seen": "2026-01-15",
  "last_seen": "2026-02-20",
  "attribution_windows": {
    "7d": {"signals": 18, "hit_rate": 0.72, "max_drawdown_pct": -3.1},
    "30d": {"signals": 62, "hit_rate": 0.67, "max_drawdown_pct": -8.4},
    "90d": {"signals": 142, "hit_rate": 0.61, "max_drawdown_pct": -14.2}
  },
  "note": "Historical attribution data. Not a predictive rating. Agent decides weighting."
}
```

**Response** (`200`, unknown producer):
```json
{
  "producer_id": "unknown_source",
  "has_provenance": false,
  "note": "No provenance data available. Proceeding without attribution context."
}
```

See: [oracle.md](oracle.md).

---

## MCP

### GET `/api/v1/mcp/producers`

```http
GET /api/v1/mcp/producers
Authorization: Bearer <token>
```

Response:

```json
{
  "producers": [
    {
      "name": "tradfi_basis",
      "domain": "tradfi",
      "mcp_source_url": null,
      "description": "...",
      "assets": ["BTC", "ETH", "SOL"],
      "schedule": "*/15 * * * *",
      "registered_at": "2026-03-01T05:00:00Z",
      "latest_signal": {
        "producer": "tradfi_basis",
        "domain": "tradfi",
        "asset": "BTC",
        "direction": "long",
        "confidence": 0.72,
        "horizon": "4h",
        "reason": "Basis unwound to 1.8%, funding 0.9% — re-leveraging setup",
        "timestamp": "2026-03-01T05:00:00Z",
        "raw_score": 7.2,
        "metadata": {}
      }
    }
  ],
  "count": 1
}
```

### GET `/api/v1/mcp/status`

```http
GET /api/v1/mcp/status
Authorization: Bearer <token>
```

Response:

```json
{
  "enabled": true,
  "producer_count": 13,
  "total_signals_buffered": 847,
  "registry_ok": true
}
```

If `mcp.require_auth=true`, include `X-MCP-Key: <key>` in addition to bearer auth.
