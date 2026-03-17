---
title: "Curator Pipeline"
description: "Submit operator intelligence as structured signals to the brain."
---

# Curator Pipeline

The curator pipeline is how human intelligence enters b1e55ed.

An operator observes something — a whale move, a narrative shift, an on-chain anomaly — and submits it. The engine structures it, attributes it, and feeds it to the brain.

## CLI (fastest path)

```bash
b1e55ed signal "Whale cluster accumulating SOL — 3 wallets, $2M+ in 48h" \
  --symbols SOL \
  --direction bullish \
  --conviction 7
```

Arguments:
- `--symbols` — comma-separated asset list
- `--direction` — `bullish`, `bearish`, or `neutral`
- `--conviction` — 0–10 score for signal strength
- `--source` — optional source label (default: `operator`)

From file:

```bash
b1e55ed signal add --file ./intel.txt --symbols BTC,ETH --direction bullish
```

## API

```bash
POST /api/v1/signals/submit
Authorization: Bearer <token>

{
  "event_type": "signal.curator.v1",
  "node_id": "your-node-id",
  "source": "operator:telegram",
  "payload": {
    "symbol": "BTC",
    "direction": "bullish",
    "conviction": 7.0,
    "rationale": "Whale cluster accumulating"
  }
}
```

## Attribution

Curator signals are attributed to contributors via `node_id`. If the node_id matches a registered contributor, the signal is linked to their attribution record and counts toward their score.

See: [contributors.md](contributors.md) for contributor registration.

## How it weights

Curator signals enter the brain synthesis as the `curator` domain. Default weight: 0.25 (configurable).

See: [configuration.md](configuration.md) → `weights.curator`

## Conviction scale

| Score | Meaning |
|-------|---------|
| 8–10 | Strong conviction, multiple data points confirming |
| 5–7 | Moderate signal, single strong indicator |
| 2–4 | Weak signal, exploratory |
| 0–1 | Noise floor — barely registers |

The engine uses conviction to scale how much the signal moves the synthesis output.
