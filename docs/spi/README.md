# SPI — External Producer Guide

**Standard Producer Interface v1 · b1e55ed**

---

## What is the SPI?

The Standard Producer Interface (SPI) is b1e55ed's open attribution protocol for external signal producers. It lets anyone with a directional edge submit market signals and receive verifiable attribution — a permanent, scored record of what you called, when, and how right you were.

**Why it exists:** b1e55ed's brain synthesizes signals from multiple sources. The SPI is the public ingress for external producers who want their signals included, attributed, and scored on-chain.

**What you get as a producer:**

- **Karma tracking** — a running reputation score reflecting your calibrated accuracy
- **Attribution** — every signal permanently linked to your producer identity
- **Signal history** — full record of submissions, outcomes, and scoring deltas
- **Network weight** — higher karma → higher influence on synthesized outputs

---

## Two Integration Modes

| Mode | How it works | Best for |
|------|-------------|----------|
| **Native (push)** | You call our API directly with your signals | New integrations, full control |
| **Adapter (pull)** | We poll your existing API and normalize it | Producers with an existing signal endpoint |

Both modes produce identical internal outcomes. Native is recommended for new integrations.

---

## Quick Start — Native Mode

### Step 1: Get registered

Contact the operator to request registration, or if you have server access:

```bash
b1e55ed spi register --producer-id yourname --name "Your Name"
```

You'll receive:
- Your `producer_id` (e.g. `sendoeth`)
- Your API key: `spi_key_xxxxxxxxxxxxxxxx`

**Store the API key immediately** — it's shown once and not recoverable.

### Step 2: Submit your first signal

```bash
curl -X POST https://your-node/api/v1/spi/signals \
  -H "X-Producer-Key: spi_key_your_key_here" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTC-USD",
    "direction": "bullish",
    "confidence": 0.82,
    "horizon_hours": 168,
    "client_signal_id": "your-unique-id-001"
  }'
```

**Response (201 Created):**
```json
{
  "signal_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "accepted",
  "attribution_window_end": "2026-03-23T21:00:00Z"
}
```

### Step 3: Monitor your karma

```bash
curl https://your-node/api/v1/spi/producers/yourname/karma \
  -H "X-Producer-Key: spi_key_your_key_here"
```

---

## Signal Format

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `symbol` | string | ✅ | Asset identifier: `BTC-USD`, `ETH-USD`, `SOL-USD` |
| `direction` | string | ✅ | `"bullish"` \| `"bearish"` \| `"neutral"` |
| `confidence` | float | ✅ | Your probability estimate: `[0.55, 0.99]` |
| `horizon_hours` | int | ✅ | Resolution window in hours: `24`, `48`, `168` (7d), `720` (30d) |
| `client_signal_id` | string | ❌ | Your idempotency key — prevents duplicate submissions |

### Confidence Calibration

**What confidence means:** `P(direction correct within horizon)`. A confidence of `0.72` means "I believe there's a 72% chance this asset moves in the stated direction within the horizon window."

**Why to avoid extremes (> 0.95):** The Brier scoring system penalizes overconfidence sharply. A call at 0.97 that's wrong costs you far more karma than a call at 0.75 that's wrong. Reserve high confidence for your highest-conviction, multi-confirmed setups.

**Why 0.55 minimum:** Below 0.55, the signal is statistically indistinguishable from noise. The system won't accept it.

**Practical examples:**
- "BTC probably up this week, decent setup" → `0.65`
- "Strong confluence, multiple signals aligned" → `0.75`
- "Highest conviction call of the month" → `0.85`
- "I know something definitive" → `0.90` *(use sparingly)*

**Avoid uniform confidence.** If you always submit `0.70`, the system detects it. Genuine probability estimates vary.

---

## Lifecycle States

Your producer account progresses through states based on activity and performance:

```
onboarding → shadow → active
                ↓
            suspended → (operator review) → active
                ↓
             retired
```

| State | Trigger | What it means |
|-------|---------|---------------|
| `onboarding` | Just registered | Signals accepted, not yet scored |
| `shadow` | 5+ signals submitted | Karma tracking begins; signals scored but not public |
| `active` | 10+ resolved signals + karma ≥ 0.55 | Full participation; signals enter synthesis |
| `suspended` | Karma < 0.30 for 3+ epochs, or signal spam | Submissions rejected until operator review |
| `retired` | Manual deactivation | Account closed |

**Karma floor:** `0.30`. Drop below this and stay there — you get suspended. The system is designed to reward calibrated accuracy over time, not lucky streaks.

---

## Karma & Scoring

Karma is your reputation score. It starts at `0.50` and moves based on your forecast accuracy.

**How it works (plain English):**

1. You submit a signal: "BTC bullish, 7d, confidence 0.80"
2. After 7 days, the system checks: did BTC go up?
3. If yes → your Brier score for that signal is good → karma goes up
4. If no → Brier score is bad (especially bad given 0.80 confidence) → karma goes down
5. The more confident your correct calls, the more karma you gain
6. The more confident your wrong calls, the more karma you lose

**Karma dynamics:**
- A few accurate, well-calibrated calls → karma rises toward `0.70+`
- Uniform confidence with poor accuracy → karma grinds down
- Extreme overconfidence on wrong calls → karma drops sharply
- Accurate calls at moderate confidence → slow, steady karma gains

**Epoch:** 1 week. Karma updates happen at epoch boundaries based on all resolved signals.

**Auto-suspend:** If karma stays below `0.30` for 3+ consecutive epochs, your account is suspended automatically. Contact the operator to review.

---

## API Reference

All endpoints are under `/api/v1/spi/`. Native producers authenticate with `X-Producer-Key: spi_key_*`.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/spi/signals` | X-Producer-Key | Submit a signal |
| `GET` | `/api/v1/spi/signals` | X-Producer-Key | List your signals |
| `GET` | `/api/v1/spi/producers/{id}/karma` | X-Producer-Key | Get karma state |
| `POST` | `/api/v1/spi/producers` | Admin only | Register a new producer |

### POST /api/v1/spi/signals

Submit a directional signal.

**Request:**
```json
{
  "symbol": "BTC-USD",
  "direction": "bullish",
  "confidence": 0.82,
  "horizon_hours": 168,
  "client_signal_id": "optional-your-id-here"
}
```

**Response 201 — accepted (new signal):**
```json
{
  "signal_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "accepted",
  "attribution_window_end": "2026-03-23T21:00:00Z"
}
```

**Response 409 — duplicate (already accepted):**
```json
{
  "signal_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "duplicate"
}
```
A `409` on a duplicate `client_signal_id` is **idempotent and safe** — your signal was already accepted. Do not retry.

### GET /api/v1/spi/signals

List signals you've submitted. Supports pagination.

**Query params:**
- `limit` — max results (default: 50)
- `offset` — pagination offset (default: 0)
- `symbol` — filter by symbol

### GET /api/v1/spi/producers/{id}/karma

Get your current karma state.

**Response:**
```json
{
  "producer_id": "sendoeth",
  "lifecycle_state": "active",
  "karma": 0.63,
  "signals_submitted": 47,
  "signals_resolved": 31,
  "epoch_current": 8
}
```

---

## Error Codes

| Status | Code | Meaning |
|--------|------|---------|
| `201` | — | Signal accepted (new) |
| `409` | — | Duplicate `client_signal_id` — already accepted, idempotent |
| `400` | `spi.invalid_signal` | Bad direction/confidence/symbol |
| `403` | `spi.missing_key` | No `X-Producer-Key` header |
| `403` | `spi.unknown_key` | Invalid or unknown API key |
| `422` | — | Validation error (missing required fields) |
| `429` | `spi.quota_exceeded` | Rate limit hit (>100 signals/hour) |

---

## Adapter Mode (Advanced)

If you have an existing REST API that already serves signals, the operator can configure b1e55ed to poll your endpoint and normalize responses into SPI-equivalent internal records — no code changes on your end.

**How it works:**
1. Operator writes a YAML spec pointing at your endpoint
2. b1e55ed polls your API on a configured interval (e.g. every 60 seconds)
3. Your responses are normalized against a field mapping
4. Normalized signals feed the same internal admission pipeline as native signals

**You still get:** karma tracking, attribution, signal history — identical to native mode.

**Reference spec:** `engine/external/specs/post_fiat_signals.yaml`

See [Adapter Spec](./adapter-spec.md) for the full YAML format.

---

## Best Practices

**Use `client_signal_id` always.** Generate a unique ID on your side before calling the API. If the network request fails and you retry, you won't create a duplicate. Use a UUID or your own signal hash.

**Rate limit yourself.** The system enforces a hard cap of 100 signals/hour. Hitting it is a spam signal and can trigger suspension. If you have a high-frequency feed, filter to your highest-conviction calls.

**Vary confidence authentically.** Uniform confidence (every signal at 0.70) is detectable and signals poor calibration. Let your confidence reflect your actual conviction — it makes your high-confidence calls more valuable.

**Aim for diversity.** Signals across multiple symbols and horizons score better than a concentrated feed. A mix of 24h, 48h, and 168h horizons makes your attribution record more robust.

**Start conservative.** In `shadow` mode (your first 5–10 signals), you're not public yet. Use this as calibration time — submit at honest confidence levels and see how your Brier scores evolve before going active.

---

## Questions?

- **Spec:** [`docs/spi/interface-spec.md`](./interface-spec.md)
- **Adapter format:** [`docs/spi/adapter-spec.md`](./adapter-spec.md)
- **Full interface contract:** [`docs/spi/interface-spec.md`](./interface-spec.md)
- **Contact:** Reach the operator to request registration or raise issues
