# SPI Interface Specification

**Standard Producer Interface v1 — Formal Contract**

**Protocol version:** `spi/v1`  
**Status:** Normative  
**Stability:** Stable (additions only — no breaking changes without major version bump)

---

## Agent-First Interface Summary

For LLM agents and automated systems, the minimal interface is:

```
# SPI — Standard Producer Interface v1

Submit signals: POST /api/v1/spi/signals
  Required headers: X-Producer-Key: spi_key_*
  Body: {"symbol": "BTC-USD", "direction": "bullish|bearish|neutral", "confidence": 0.55-0.99, "horizon_hours": 24-720}

Check karma: GET /api/v1/spi/producers/{producer_id}/karma
  Required headers: X-Producer-Key: spi_key_*
```

---

## 1. Signal Payload Schema

### 1.1 Submission Request (JSON Schema)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://b1e55ed.permanentupperclass.com/schemas/spi/v1/signal-submit.json",
  "title": "SPI Signal Submission",
  "description": "Directional market signal submitted by an authenticated producer",
  "type": "object",
  "required": ["symbol", "direction", "confidence", "horizon_hours"],
  "additionalProperties": false,
  "properties": {
    "symbol": {
      "type": "string",
      "description": "Asset identifier. Format: BASE-QUOTE (e.g. BTC-USD, ETH-USD, SOL-USD)",
      "pattern": "^[A-Z0-9]+-[A-Z0-9]+$",
      "examples": ["BTC-USD", "ETH-USD", "SOL-USD", "WIF-USD"]
    },
    "direction": {
      "type": "string",
      "enum": ["bullish", "bearish", "neutral"],
      "description": "Directional assertion for the symbol within the horizon window"
    },
    "confidence": {
      "type": "number",
      "minimum": 0.55,
      "maximum": 0.99,
      "description": "Producer's probability estimate that direction is correct. P(direction | horizon). Must be in [0.55, 0.99]."
    },
    "horizon_hours": {
      "type": "integer",
      "minimum": 24,
      "maximum": 720,
      "description": "Forecast horizon in hours. The attribution window closes this many hours after submission.",
      "examples": [24, 48, 72, 168, 336, 720]
    },
    "client_signal_id": {
      "type": "string",
      "maxLength": 255,
      "description": "Producer-side idempotency key. If provided, duplicate submissions with the same client_signal_id return 409 without creating a new record. Strongly recommended.",
      "examples": ["my-signal-2026-03-16-btc-001", "550e8400-e29b-41d4-a716-446655440000"]
    }
  }
}
```

### 1.2 Field Constraints Summary

| Field | Type | Required | Min | Max | Notes |
|-------|------|----------|-----|-----|-------|
| `symbol` | string | ✅ | 3 chars | 20 chars | `BASE-QUOTE` format |
| `direction` | enum | ✅ | — | — | `bullish`, `bearish`, `neutral` only |
| `confidence` | float | ✅ | `0.55` | `0.99` | P(correct) — not a weight |
| `horizon_hours` | int | ✅ | `24` | `720` | Hours until attribution window closes |
| `client_signal_id` | string | ❌ | — | 255 chars | Idempotency key; auto-generated if omitted |

### 1.3 Submission Acknowledgment (Response)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://b1e55ed.permanentupperclass.com/schemas/spi/v1/signal-ack.json",
  "title": "SPI Signal Acknowledgment",
  "type": "object",
  "required": ["signal_id", "status", "attribution_window_end"],
  "properties": {
    "signal_id": {
      "type": "string",
      "format": "uuid",
      "description": "Canonical internal signal ID assigned by the gateway"
    },
    "status": {
      "type": "string",
      "enum": ["accepted", "duplicate"],
      "description": "'accepted' for new signals (201); 'duplicate' when client_signal_id was already recorded (409)"
    },
    "attribution_window_end": {
      "type": "string",
      "format": "date-time",
      "description": "ISO-8601 timestamp when the forecast window closes and resolution begins"
    }
  }
}
```

---

## 2. Outcome Resolution Rules

### 2.1 Resolution Trigger

Resolution is attempted after `attribution_window_end` passes. The resolver checks whether a price feed is available for the symbol. If no price data is available within the grace period (default: 4 hours post-window-close), the signal is marked `unresolvable` and excluded from karma computation.

### 2.2 Direction Correctness

Resolution compares `entry_price` (price snapshot at admission time) to `exit_price` (TWAP price at window close):

| Submitted direction | Condition | Outcome |
|--------------------|-----------|---------|
| `bullish` | `exit_price > entry_price` | **Correct** |
| `bullish` | `exit_price ≤ entry_price` | **Incorrect** |
| `bearish` | `exit_price < entry_price` | **Correct** |
| `bearish` | `exit_price ≥ entry_price` | **Incorrect** |
| `neutral` | `\|Δprice/entry_price\| < threshold` (default 2%) | **Correct** |
| `neutral` | `\|Δprice/entry_price\| ≥ threshold` | **Incorrect** |

### 2.3 Brier Score Computation

The Brier score measures forecast calibration. For a binary event (direction correct = 1, incorrect = 0):

```
brier_score = (forecast_probability - actual_outcome)²
```

Where:
- `forecast_probability` = the submitted `confidence` value
- `actual_outcome` = `1.0` if direction was correct, `0.0` if incorrect

**Score range:** `[0.0, 1.0]`. Lower is better.
- Perfect calibrated correct call at 0.80 confidence: `(0.80 - 1.0)² = 0.04`
- Perfectly calibrated incorrect call at 0.80 confidence: `(0.80 - 0.0)² = 0.64`
- Coin-flip baseline: `0.25`

**Why this penalizes overconfidence:** A wrong call at `0.95` scores `(0.95)² = 0.90` — nearly maximum penalty. A wrong call at `0.60` scores `(0.60)² = 0.36` — much less damage.

### 2.4 Karma Ledger Spec

**Epoch definition:** 7 days (UTC week boundaries, Monday 00:00 UTC → Sunday 23:59 UTC).

**Initial karma:** `0.50` for all new producers.

**Per-epoch karma update:**

```
epoch_brier_mean = mean(brier_scores for all signals resolved in epoch)
karma_delta = 0.25 - epoch_brier_mean   # positive if better than coin-flip
new_karma = clip(old_karma + (smoothing_factor × karma_delta), 0.0, 1.0)
```

**Smoothing factor:** `0.15` (exponential moving average — prevents single epoch from dominating).

**Interpretation:**
- Perfect epoch (all correct, well-calibrated): `karma_delta ≈ +0.20` → karma rises
- Coin-flip epoch: `karma_delta ≈ 0` → karma unchanged
- Poor epoch (mostly wrong or overconfident): `karma_delta < 0` → karma falls

**Thresholds:**

| Threshold | Value | Effect |
|-----------|-------|--------|
| Shadow activation | 5 signals submitted | Karma tracking begins |
| Active activation | karma ≥ 0.55 + 10 resolved signals | Promoted to `active` |
| Suspend trigger | karma < 0.30 for 3 consecutive epochs | Auto-suspend |
| Auto-suspend floor | karma = 0.30 | Hard threshold |

---

## 3. Idempotency Contract

### 3.1 `client_signal_id` Behavior

If a submission includes a `client_signal_id`:

1. The gateway hashes the combination `(producer_id, client_signal_id)` as a deduplication key.
2. On first submission: the signal is created, stored, and `201 Created` is returned.
3. On subsequent submissions with the same `client_signal_id`:
   - `409 Conflict` is returned
   - The response body contains the original `signal_id` and `status: "duplicate"`
   - No new signal record is created
   - No karma impact from the duplicate

**Contract:** A `409` response is NOT an error. It means "your signal was already accepted." Treat it identically to a `201` — the signal exists in the system.

### 3.2 Auto-Generated IDs

If `client_signal_id` is omitted, the gateway generates a UUID internally. In this case, duplicate HTTP requests create duplicate signal records. Use `client_signal_id` to prevent this.

### 3.3 Idempotency Window

Idempotency records are permanent (no expiry). A `client_signal_id` submitted in epoch 1 will still return `409` in epoch 100.

---

## 4. Error Taxonomy

All error responses follow this envelope:

```json
{
  "code": "spi.error_code",
  "message": "Human-readable description",
  "status": 400
}
```

| HTTP Status | Code | When |
|-------------|------|------|
| `201` | — | Signal accepted (new) |
| `400` | `spi.invalid_signal` | Direction not in `{bullish,bearish,neutral}`, confidence out of range, symbol malformed |
| `403` | `spi.missing_key` | `X-Producer-Key` header absent |
| `403` | `spi.unknown_key` | Key doesn't match any registered producer |
| `403` | `spi.suspended` | Producer account is suspended |
| `409` | — | Duplicate `client_signal_id` — idempotent, contains original `signal_id` |
| `422` | — | Missing required fields (Pydantic validation failure) |
| `429` | `spi.quota_exceeded` | Hourly quota exceeded (default: 100 signals/hour) |
| `500` | `spi.internal_error` | Gateway-side fault — safe to retry with exponential backoff |

### Retry Policy

| Status | Retry? | Notes |
|--------|--------|-------|
| `201` | No | Already accepted |
| `400` | No | Fix the payload |
| `403` | No | Fix credentials or contact operator |
| `409` | No | Already accepted — treat as success |
| `422` | No | Fix the payload |
| `429` | Yes, after 60s | Back off; don't burst |
| `500` | Yes, with backoff | Transient fault — exponential backoff recommended |

---

## 5. Authentication

### 5.1 API Key Format

All SPI API keys are prefixed with `spi_key_` followed by 64 hex characters:

```
spi_key_a1b2c3d4...  (total: 72 characters)
```

Keys are stored as SHA-256 hashes server-side. The plaintext key is shown exactly once at registration and cannot be recovered.

### 5.2 Header

```
X-Producer-Key: spi_key_your_key_here
```

The header name is case-insensitive in HTTP/2 but the canonical form uses this casing.

### 5.3 Key Rotation

If a key is compromised, contact the operator for manual rotation. Automated rotation is a v1.1 feature.

---

## 6. Versioning

### 6.1 Protocol Version

Current version: `spi/v1`

All endpoints are mounted under `/api/v1/`. Future breaking changes will increment to `/api/v2/`.

### 6.2 Compatibility Policy

- **Additive changes** (new optional fields, new endpoints): No version bump. Backward compatible.
- **Breaking changes** (removed fields, changed semantics): Major version bump. Both versions maintained for ≥ 6 months.
- **Schema version field:** Signal payloads MAY include `"schema_version": "spi.v1"`. Currently informational; will be required if/when v2 is deployed alongside v1.

### 6.3 Forward Compatibility

Gateways MUST ignore unknown fields in submission bodies. Producers MUST ignore unknown fields in response bodies. This allows both sides to evolve independently within a major version.

---

## 7. Rate Limits and Quotas

| Lifecycle State | Hourly Signal Quota | Burst (per minute) |
|-----------------|--------------------|--------------------|
| `onboarding` | 10 | 5 |
| `shadow` | 50 | 20 |
| `active` | 100 | 50 |
| `suspended` | 0 | 0 |

Quota violations return `429 spi.quota_exceeded`. Repeated quota violations trigger the spam slash condition and accelerate suspension.

---

## 8. Symbol Registry

The SPI accepts any `BASE-QUOTE` symbol string. However, signals on illiquid or unsupported symbols may be marked `unresolvable` if no price feed is available at resolution time. This does not penalize karma — the signal is simply excluded from scoring.

Commonly supported symbols: `BTC-USD`, `ETH-USD`, `SOL-USD`, `WIF-USD`, `BONK-USD`, `JUP-USD`.

Check with the operator for the current supported symbol list.

---

## 9. Signal Lifecycle

```
submitted → validated → accepted → [window_open] → [window_close] → resolving → resolved
                ↓                                                        ↓
            rejected                                               unresolvable
```

| State | Description |
|-------|-------------|
| `submitted` | Received by gateway, pending validation |
| `validated` | Passed schema and semantic validation |
| `accepted` | Written to spi_signals, idempotency key stored |
| `window_open` | Attribution window active — no changes allowed |
| `resolving` | Window closed, resolver fetching price data |
| `resolved` | Brier score computed, karma delta applied |
| `rejected` | Failed validation (never stored in main ledger) |
| `unresolvable` | No price data available — excluded from scoring |
