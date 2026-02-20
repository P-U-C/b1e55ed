# API Reference

REST API for b1e55ed.

## Base URL

```text
http://localhost:5050/api/v1/
```

## Authentication

All endpoints except `GET /health` require a bearer token.

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

When b1e55ed raises a structured API error, responses follow:

```json
{
  "error": {
    "code": "...",
    "message": "..."
  }
}
```

Notes:
- Some endpoints may also return FastAPI `HTTPException` errors using `{"detail": "..."}`.
- `code` values are stable identifiers intended for automation.

---

## Health

### GET `/health`

Liveness endpoint. Does not require authentication.

**Response** (`200`):
```json
{
  "version": "1.0.0-beta.2",
  "uptime_seconds": 12.34,
  "db_size_bytes": 123456
}
```

---

## Brain

### GET `/brain/status`

Returns current brain state derived from events.

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

**Errors**:
- `401` `auth.missing_token|auth.invalid_header|auth.invalid_token`

### POST `/brain/run`

Runs one brain cycle synchronously.

Kill switch gating:
- If kill switch level is `> 0`, this endpoint is blocked.

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

**Errors**:
- `401` `auth.*`
- `423` `kill_switch.active` (includes `level`)

---

## Signals

### GET `/signals`

Lists recent signal events.

**Query params**:
- `domain` (optional): filters by `signal.<domain>.*`.
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
      "payload": {
        "symbol": "BTC",
        "rsi_14": 52.1
      }
    }
  ],
  "limit": 100,
  "offset": 0,
  "total": 1
}
```

**Errors**:
- `401` `auth.*`

### POST `/signals/submit`

Submit a signal event with contributor attribution.

This endpoint:
- requires `event_type` to be `signal.*`
- resolves the contributor by `node_id`
- stores attribution in `contributor_signals`

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
{
  "event_id": "123",
  "contributor_id": "contrib_abc123"
}
```

**Errors**:
- `400` `signal.invalid_type`
- `404` `contributor.not_found`
- `401` `auth.*`

---

## Positions

### GET `/positions`

Lists positions.

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

Returns a single position.

**Errors**:
- `404` `{"detail":"Position not found"}`
- `401` `auth.*`

---

## Producers

### GET `/producers/status`

Returns health and last run metadata for known producers.

**Response** (`200`):
```json
{
  "producers": {
    "ta": {
      "name": "ta",
      "domain": "technical",
      "schedule": "*/15 * * * *",
      "endpoint": "http://...",
      "healthy": true,
      "last_run_at": "2026-02-20T00:00:00+00:00",
      "last_success_at": "2026-02-20T00:00:00+00:00",
      "last_error": null,
      "consecutive_failures": 0,
      "events_produced": 0,
      "avg_duration_ms": null,
      "expected_interval_ms": null,
      "updated_at": "2026-02-20T00:00:00+00:00"
    }
  }
}
```

### GET `/producers/`

Lists registered producers (database-backed registrations).

**Response** (`200`):
```json
{
  "producers": [
    {
      "name": "example",
      "domain": "onchain",
      "endpoint": "https://...",
      "schedule": "*/15 * * * *",
      "registered_at": "2026-02-20T00:00:00+00:00"
    }
  ]
}
```

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

**Response** (`200`):
```json
{
  "name": "example",
  "domain": "onchain",
  "endpoint": "https://example.internal/poll",
  "schedule": "*/15 * * * *",
  "registered_at": "2026-02-20T00:00:00+00:00"
}
```

**Errors**:
- `409` `producer.duplicate`

### DELETE `/producers/{name}`

Deregisters a producer.

**Response** (`200`):
```json
{"removed": "example"}
```

**Errors**:
- `404` `producer.not_found`

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
  "metadata": {
    "public_key": "...",
    "eas": {"uid": "0x..."}
  }
}
```

**Errors**:
- `409` `contributor.duplicate`

### GET `/contributors/{id}`

Returns a contributor.

**Errors**:
- `404` `contributor.not_found`

### DELETE `/contributors/{id}`

Removes a contributor.

**Errors**:
- `404` `contributor.not_found`

### GET `/contributors/{id}/score`

Computes contributor score from attribution tables.

**Errors**:
- `404` `contributor.not_found`

### GET `/contributors/leaderboard`

Returns the top contributors.

**Query params**:
- `limit` (default 20)

### GET `/contributors/attestations`

Lists contributors with an EAS UID in metadata.

### GET `/contributors/{id}/attestation`

Returns the stored off-chain EAS attestation for a contributor.

**Errors**:
- `404` `contributor.attestation_not_found|contributor.not_found`

---

## Karma / Treasury

### GET `/treasury`

Returns karma state derived from config and DB.

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
{
  "intent_ids": ["1", "2"],
  "tx_hash": "0xabc..."
}
```

### GET `/karma/receipts`

Lists settlement receipts.

---

## Regime

### GET `/regime`

Returns current regime and last change timestamp.

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

Returns the current in-memory configuration.

### POST `/config/validate`

Validates a config payload (does not persist).

### POST `/config`

Validates and writes `config/user.yaml`, and updates the in-process config.

---

## Webhooks

Webhook subscriptions are implemented in the engine (`engine.core.webhooks`) and managed via the CLI.

There are no REST endpoints for webhook subscription management in this version.
