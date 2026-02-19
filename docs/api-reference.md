# API Reference

REST API for b1e55ed trading intelligence system.

## Base URL

```
http://localhost:5050
```

## Authentication

Optional bearer token authentication:

```bash
# Set in config
api:
  auth_token: "your-secret-token"

# Or environment variable
export B1E55ED_API__AUTH_TOKEN="your-secret-token"

# Use in requests
curl -H "Authorization: Bearer your-secret-token" http://localhost:5050/api/endpoint
```

## Endpoints

### Health

#### GET `/health`

System health check.

**Response:**
```json
{
  "status": "ok",
  "uptime_seconds": 123.45,
  "database": "connected",
  "version": "1.0.0-beta.1"
}
```

**Status Codes:**
- `200` - System healthy
- `503` - System degraded

---

### Brain

#### GET `/brain/status`

Current brain state and last cycle results.

**Response:**
```json
{
  "last_cycle_at": "2026-02-18T23:00:00Z",
  "regime": "EARLY_BULL",
  "regime_changed_at": "2026-02-15T10:30:00Z",
  "kill_switch_level": 0,
  "kill_switch_changed_at": null,
  "positions_open": 2,
  "positions_closed_24h": 1
}
```

#### POST `/brain/run`

Trigger brain cycle manually (out-of-band from cron).

**Response:**
```json
{
  "cycle_id": "550e8400-e29b-41d4-a716-446655440000",
  "started_at": "2026-02-18T23:00:00Z",
  "completed_at": "2026-02-18T23:00:23Z",
  "duration_ms": 23456,
  "symbols_analyzed": ["BTC", "ETH", "SOL"],
  "convictions_generated": 2,
  "intents_created": 1
}
```

---

### Signals

#### GET `/signals`

List recent signals from producers.

**Query Parameters:**
- `domain` (optional) - Filter by domain (technical, onchain, tradfi, social, events, curator)
- `limit` (default: 100, max: 500) - Number of results
- `offset` (default: 0) - Pagination offset

**Response:**
```json
{
  "total": 450,
  "limit": 100,
  "offset": 0,
  "items": [
    {
      "id": "sig_123",
      "type": "signal.ta.v1",
      "symbol": "BTC",
      "domain": "technical",
      "score": 0.75,
      "metadata": {
        "rsi_14": 55.0,
        "trend_strength": 0.8
      },
      "created_at": "2026-02-18T22:55:00Z",
      "producer": "ta"
    }
  ]
}
```

**Examples:**
```bash
# All signals
curl http://localhost:5050/signals

# Only on-chain signals
curl http://localhost:5050/signals?domain=onchain

# Paginate
curl http://localhost:5050/signals?limit=50&offset=100
```

---

### Positions

#### GET `/positions`

List open and recent closed positions.

**Response:**
```json
{
  "items": [
    {
      "id": "pos_abc123",
      "platform": "hyperliquid",
      "asset": "BTC",
      "direction": "long",
      "entry_price": 95000.0,
      "current_price": 96500.0,
      "size_notional": 1500.0,
      "leverage": 2.0,
      "pnl_usd": 23.68,
      "pnl_pct": 0.0158,
      "stop_loss": 93000.0,
      "take_profit": 98000.0,
      "opened_at": "2026-02-18T20:00:00Z",
      "status": "open"
    }
  ]
}
```

#### GET `/positions/{position_id}`

Get specific position details.

**Response:**
```json
{
  "id": "pos_abc123",
  "platform": "hyperliquid",
  "asset": "BTC",
  "direction": "long",
  "entry_price": 95000.0,
  "size_notional": 1500.0,
  "leverage": 2.0,
  "margin_type": "isolated",
  "stop_loss": 93000.0,
  "take_profit": 98000.0,
  "opened_at": "2026-02-18T20:00:00Z",
  "status": "open",
  "conviction_score": 0.82,
  "regime_at_entry": "EARLY_BULL"
}
```

---

### Regime

#### GET `/regime`

Current market regime and recent changes.

**Response:**
```json
{
  "regime": "EARLY_BULL",
  "regime_class": "bullish",
  "changed_at": "2026-02-15T10:30:00Z",
  "duration_hours": 80,
  "confidence": 0.85,
  "features": {
    "btc_trend": 0.75,
    "funding_rate": 0.012,
    "fear_greed": 65,
    "volatility": 0.35
  }
}
```

**Regime Types:**
- `EARLY_BULL` - Emerging uptrend
- `BULL` - Confirmed bull market
- `CHOP` - Sideways/ranging
- `BEAR` - Downtrend
- `CRISIS` - Extreme volatility/crash

---

### Producers

#### GET `/producers/status`

Health status of all signal producers.

**Response:**
```json
{
  "producers": {
    "ta": {
      "name": "ta",
      "domain": "technical",
      "schedule": "*/5 * * * *",
      "last_run_at": "2026-02-18T22:55:00Z",
      "last_success_at": "2026-02-18T22:55:00Z",
      "last_error": null,
      "consecutive_failures": 0,
      "events_produced": 12450,
      "avg_duration_ms": 250,
      "expected_interval_ms": 300000,
      "health": "healthy"
    }
  },
  "summary": {
    "total": 13,
    "healthy": 12,
    "degraded": 1,
    "failing": 0
  }
}
```

**Health States:**
- `healthy` - Normal operation
- `degraded` - Some failures, still producing
- `failing` - Multiple consecutive failures

---

### Config

#### GET `/config`

Current system configuration (secrets redacted).

**Response:**
```json
{
  "preset": "balanced",
  "weights": {
    "curator": 0.25,
    "onchain": 0.25,
    "tradfi": 0.20,
    "social": 0.15,
    "technical": 0.10,
    "events": 0.05
  },
  "risk": {
    "max_drawdown_pct": 0.30,
    "max_daily_loss_usd": 240.0,
    "max_position_size_pct": 0.15
  },
  "execution": {
    "mode": "paper"
  }
}
```

#### POST `/config/validate`

Validate config changes before applying.

**Request:**
```json
{
  "weights": {
    "curator": 0.30,
    "onchain": 0.25,
    "tradfi": 0.20,
    "social": 0.10,
    "technical": 0.10,
    "events": 0.05
  }
}
```

**Response:**
```json
{
  "valid": true,
  "warnings": [],
  "errors": []
}
```

**Error Example:**
```json
{
  "valid": false,
  "errors": [
    "Domain weights must sum to 1.0 (got 0.95)"
  ]
}
```

---

### Karma

#### GET `/karma/treasury`

Karma treasury status and pending intents.

**Response:**
```json
{
  "treasury_address": "0xb1e55ed...",
  "percentage": 0.005,
  "pending_intents": 3,
  "pending_amount_usd": 12.50,
  "lifetime_receipts": 8,
  "lifetime_total_usd": 456.78
}
```

#### GET `/karma/intents`

List pending karma intents (profit-sharing obligations).

**Response:**
```json
{
  "items": [
    {
      "id": "intent_123",
      "position_id": "pos_abc",
      "profit_usd": 500.0,
      "karma_usd": 2.50,
      "created_at": "2026-02-18T20:00:00Z",
      "settled": false
    }
  ]
}
```

#### POST `/karma/settle`

Settle pending intents (create on-chain transaction).

**Request:**
```json
{
  "intent_ids": ["intent_123", "intent_456"],
  "tx_hash": "0xabc..." 
}
```

**Response:**
```json
{
  "receipt_id": "receipt_789",
  "total_usd": 5.00,
  "intents_settled": 2,
  "tx_hash": "0xabc..."
}
```

---

### Social

#### GET `/social/sentiment`

Current social sentiment signals.

**Response:**
```json
{
  "items": [
    {
      "symbol": "BTC",
      "sentiment_score": 0.65,
      "velocity": 0.82,
      "sources": ["tiktok", "reddit"],
      "updated_at": "2026-02-18T22:50:00Z"
    }
  ]
}
```

#### GET `/social/alerts`

Recent social alerts (viral content, contrarian signals).

**Response:**
```json
{
  "items": [
    {
      "type": "contrarian_signal",
      "symbol": "SOL",
      "message": "Extreme bearish sentiment (95% negative) → potential reversal",
      "severity": "medium",
      "created_at": "2026-02-18T22:45:00Z"
    }
  ]
}
```

---

## Error Responses

### 400 Bad Request
```json
{
  "detail": "Invalid query parameter: domain must be one of [technical, onchain, tradfi, social, events, curator]"
}
```

### 401 Unauthorized
```json
{
  "detail": "Invalid authorization header"
}
```

### 404 Not Found
```json
{
  "detail": "Position pos_xyz not found"
}
```

### 500 Internal Server Error
```json
{
  "detail": "Database error: ..."
}
```

## Rate Limits

No rate limits on localhost. For production deployments, consider:

- 100 requests/min per IP (general)
- 10 requests/min for `/brain/run` (expensive)

Implement via nginx:

```nginx
limit_req_zone $binary_remote_addr zone=api:10m rate=100r/m;

location /brain/run {
    limit_req zone=api burst=5;
}
```

## Webhook Support

Coming in v1.1.0:
- Register webhooks for events (position opened/closed, kill switch triggered)
- Deliver via HTTP POST to configured endpoints

## Client Libraries

### Python

```python
import httpx

class B1e55edClient:
    def __init__(self, base_url="http://localhost:5050", token=None):
        self.base_url = base_url
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}
    
    def get_signals(self, domain=None, limit=100):
        params = {"limit": limit}
        if domain:
            params["domain"] = domain
        resp = httpx.get(f"{self.base_url}/signals", params=params, headers=self.headers)
        return resp.json()
    
    def trigger_brain_cycle(self):
        resp = httpx.post(f"{self.base_url}/brain/run", headers=self.headers)
        return resp.json()

# Usage
client = B1e55edClient(token="your-token")
signals = client.get_signals(domain="onchain")
```

### JavaScript

```javascript
class B1e55edClient {
  constructor(baseUrl = 'http://localhost:5050', token = null) {
    this.baseUrl = baseUrl;
    this.headers = token ? { 'Authorization': `Bearer ${token}` } : {};
  }

  async getSignals(domain = null, limit = 100) {
    const params = new URLSearchParams({ limit });
    if (domain) params.append('domain', domain);
    
    const resp = await fetch(`${this.baseUrl}/signals?${params}`, {
      headers: this.headers
    });
    return resp.json();
  }
}

// Usage
const client = new B1e55edClient('http://localhost:5050', 'your-token');
const signals = await client.getSignals('onchain');
```

## Next Steps

- [Getting Started](getting-started.md) - Setup and run
- [Configuration](configuration.md) - Configure API auth
- [Deployment](deployment.md) - Production API hosting
