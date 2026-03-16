# SPI Adapter Spec Reference

**Adapter-Mediated Producer Integration**

This document is for **operators** configuring pull-mode (adapter) integrations. If you're a producer wanting to submit signals directly, see [README.md](./README.md).

---

## Overview

The adapter framework lets b1e55ed consume an external producer's existing API without requiring any changes on the producer's side. The operator writes a YAML spec that describes:

1. **Where** to find the signals (endpoint, auth, polling interval)
2. **How** to extract them (field mappings from their format to SPI format)
3. **How** to normalize them (confidence scaling, direction translation)

Once deployed, b1e55ed polls the external endpoint on the configured interval, normalizes each signal through the spec, and calls the same internal `accept_signal()` pipeline as native producers. The producer gets identical karma tracking and attribution.

---

## YAML Spec Format

### Top-Level Fields

```yaml
name: string          # Unique adapter identifier (e.g. "post-fiat-signals")
version: string       # Spec version string (e.g. "1.0.0")
domain: string        # Signal domain: "tradfi" | "defi" | "macro" | "crypto"
base_url: string      # Base URL of the producer's API. Supports ${ENV_VAR} expansion.
poll_interval_sec: int  # How often to poll (minimum: 30, default: 60)
min_confidence: float   # Discard signals below this confidence (default: 0.55)
stale_threshold_sec: int  # Age in seconds beyond which signals are skipped (default: 300)
```

### Health Endpoint (Optional but Recommended)

```yaml
health_endpoint:
  path: /health         # Path appended to base_url
  method: GET           # HTTP method
  timeout_sec: 5        # Request timeout
```

If configured, b1e55ed checks the health endpoint before polling signals. If unhealthy, the poll cycle is skipped (no error logged to producer karma).

### Authentication

```yaml
auth:
  type: bearer | api_key | basic | none
  # For bearer:
  token: "${API_TOKEN}"
  # For api_key:
  header: "X-API-Key"
  value: "${API_KEY}"
  # For basic:
  username: "${API_USER}"
  password: "${API_PASS}"
```

Environment variables in `${VAR}` syntax are expanded at runtime. Never hardcode credentials in the YAML file.

### Signals Endpoint

```yaml
signals_endpoint:
  path: /signals/filtered    # Path appended to base_url
  method: GET | POST
  params:                    # Query parameters (GET) or body fields (POST)
    filter: ACTIONABLE
  timeout_sec: 10
```

### Items Path

```yaml
items_path: "signals"        # JSON path to the array of signal objects in the response
```

The adapter extracts `response.signals` as the signal list. Use dot notation for nested paths: `"data.items.signals"`.

### Field Mapping

```yaml
field_mapping:
  # Maps SPI field names to the producer's field names in each signal object
  symbol: "ticker"           # Producer's field name → SPI "symbol"
  direction: "action"        # Producer's field → SPI "direction" (see Direction Mapping)
  confidence: "confidence"   # Producer's field → SPI "confidence" (see Confidence Normalization)
  horizon_hours: "168"       # Literal value OR producer field name
  observed_at: "timestamp"   # Optional: producer's timestamp field
  client_signal_id: "id"     # Optional: producer's signal ID for deduplication
```

**Literals vs field names:** If the value can be parsed as a number or is not a string key in the signal object, it's treated as a literal. `"168"` is a literal `168`. `"timestamp"` is a field lookup.

### Direction Mapping

When the producer's `direction` field uses different values from SPI's `bullish|bearish|neutral`:

```yaml
direction_mapping:
  BUY: bullish
  SELL: bearish
  HOLD: neutral
  LONG: bullish
  SHORT: bearish
  FLAT: neutral
```

If not provided, the adapter assumes the producer's values already match SPI format.

### Confidence Normalization

The producer's confidence values may be on a different scale. Configure normalization:

```yaml
confidence_normalization:
  strategy: linear_scale | logistic | passthrough
  # For linear_scale:
  input_min: 0.0
  input_max: 100.0
  output_min: 0.55
  output_max: 0.95
  # For logistic:
  midpoint: 0.5
  steepness: 10
```

#### `passthrough` (default)
Use the producer's confidence value directly. Assumes it's already in `[0.55, 0.99]`. Values outside this range are clamped.

#### `linear_scale`
Linearly rescale from the producer's range to SPI's range:
```
output = output_min + (input - input_min) / (input_max - input_min) × (output_max - output_min)
```
Example: Producer uses `[0, 100]` → `linear_scale` maps to `[0.55, 0.95]`.

#### `logistic`
Apply a logistic function to map any range to `(0, 1)`, then clamp to `[0.55, 0.99]`:
```
output = 1 / (1 + exp(-steepness × (input - midpoint)))
```
Use when the producer's confidence scale is unbounded or follows a non-linear distribution.

---

## Complete Example: post-fiat-signals

This is the reference adapter for the post-fiat-signals producer:

```yaml
name: post-fiat-signals
version: "1.0.0"
domain: tradfi
base_url: "${POST_FIAT_SIGNALS_URL}"
poll_interval_sec: 60
min_confidence: 0.55
stale_threshold_sec: 300

health_endpoint:
  path: /health
  method: GET
  timeout_sec: 5

signals_endpoint:
  path: /signals/filtered
  method: GET
  params:
    filter: ACTIONABLE
  timeout_sec: 10

items_path: "signals"

field_mapping:
  symbol: "ticker"
  direction: "action"       # "BUY"→bullish, "SELL"→bearish, "HOLD"→neutral
  confidence: "confidence"
  horizon_hours: "168"      # literal — post-fiat uses weekly horizon
  observed_at: "timestamp"
  regime: "regime"
  signal_type: "signal_type"
  hit_rate: "hit_rate"
  avg_return: "avg_return"
  is_stale: "is_stale"
  source_assertion: "action"

direction_mapping:
  BUY: bullish
  SELL: bearish
  HOLD: neutral

confidence_normalization:
  strategy: passthrough     # post-fiat already outputs [0.55, 0.99]
```

**Reading this spec:**
- Poll `${POST_FIAT_SIGNALS_URL}/signals/filtered?filter=ACTIONABLE` every 60 seconds
- Parse `response.signals` as the signal array
- Map `ticker` → symbol, `action` → direction (with BUY/SELL/HOLD translation), `confidence` → confidence
- Use literal `168` for all signals' `horizon_hours` (weekly horizon)
- Skip signals older than 300 seconds (`stale_threshold_sec`)
- Skip signals with confidence below `0.55` (`min_confidence`)

---

## Environment Variable Expansion

Any string value in the YAML can reference environment variables with `${VAR_NAME}` syntax:

```yaml
base_url: "${POST_FIAT_SIGNALS_URL}"         # full URL from env
auth:
  type: bearer
  token: "${POST_FIAT_API_TOKEN}"            # secret from env
```

**Rules:**
- Variables are expanded at adapter load time (not at each poll)
- If a referenced variable is not set, adapter startup fails with a clear error
- Variable names are case-sensitive
- Nested variables are not supported: `${${VAR}}` does not work

**Best practice:** Put the spec YAML in version control. Put environment variables in `.env` or your deployment secrets manager. Never commit credentials.

---

## Spec File Location

Place adapter specs in:

```
engine/external/specs/<adapter-name>.yaml
```

The adapter framework auto-discovers all `.yaml` files in this directory at startup.

---

## Testing a Spec

Before deploying, validate a spec and do a dry-run poll:

```bash
# Validate YAML structure and field mappings
b1e55ed adapter validate engine/external/specs/my-adapter.yaml

# Dry-run: poll once, print normalized signals without submitting
b1e55ed adapter dry-run engine/external/specs/my-adapter.yaml

# Dry-run with verbose output (shows raw response + field mappings)
b1e55ed adapter dry-run engine/external/specs/my-adapter.yaml --verbose
```

**Dry-run output example:**
```json
[
  {
    "symbol": "BTC-USD",
    "direction": "bullish",
    "confidence": 0.78,
    "horizon_hours": 168,
    "client_signal_id": "pf-btc-1710600000",
    "_source": {
      "ticker": "BTC",
      "action": "BUY",
      "confidence": 0.78,
      "timestamp": "2026-03-16T21:00:00Z"
    }
  }
]
```

---

## Common Issues

**Signals not appearing after adapter startup**

- Check health endpoint — if unhealthy, polls are skipped
- Verify `POST_FIAT_SIGNALS_URL` env var is set
- Check `stale_threshold_sec` — all signals may be older than the threshold
- Run `b1e55ed adapter dry-run` to see raw response

**Confidence values clamped to 0.55**

- Producer is returning values below `min_confidence`
- Review `confidence_normalization` — may need `linear_scale` if producer uses a different range

**Direction not mapping correctly**

- Check `direction_mapping` — producer may use different strings
- Run dry-run with `--verbose` to see the raw `action` field values

**Duplicate signals on every poll**

- Add `client_signal_id` to field_mapping pointing to the producer's signal ID
- Without this, each poll cycle creates new records even if signals haven't changed

---

## Adapter vs Native Migration

Adapter mode is a bootstrap path. If you're a producer currently integrated via adapter and want to switch to native (push) mode:

1. Contact the operator — your producer record already exists, the adapter just gets disabled
2. Implement the POST `/api/v1/spi/signals` call in your system
3. Operator provides your `spi_key_*` and marks your ingress mode as `native`
4. Begin submitting directly

Your karma history, lifecycle state, and signal records are fully preserved across the migration.
