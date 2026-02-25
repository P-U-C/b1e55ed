# CLI Reference

Authoritative source: `engine/cli.py` (`build_parser()`).

All commands support `--help`.

---

## Core

### `b1e55ed setup`

Interactive onboarding. Writes `config/user.yaml`, initializes `data/brain.db`.

```text
b1e55ed setup [--preset conservative|balanced|degen] [--non-interactive]
```

### `b1e55ed brain`

Run one brain cycle.

```text
b1e55ed brain [--full] [--json]
```

### `b1e55ed signal`

Ingest operator intel as a curator signal.

```text
b1e55ed signal "<text>" [--symbols "BTC,ETH"] [--source "operator"] [--direction bullish|bearish|neutral] [--conviction 0-10] [--json]

b1e55ed signal add --file <path> [--symbols ...] [--source ...] [--direction ...] [--conviction ...] [--json]
```

See: [curator.md](curator.md).

### `b1e55ed alerts`

List recent alerts from the event store.

```text
b1e55ed alerts [--since <minutes>] [--json]
```

### `b1e55ed positions`

List open positions with best-effort mark price PnL.

```text
b1e55ed positions [--json]
```

---

## Analysis

### `b1e55ed kelly`

Estimate optimal position sizing from trade history using the Kelly criterion. Regime-adjusted.

```text
b1e55ed kelly [--json]
```

### `b1e55ed backtest walkforward`

Walk-forward validation with FDR-corrected results.

```text
b1e55ed backtest walkforward \
  [--symbols BTC,ETH,SOL] \
  [--strategies momentum,ma_crossover] \
  [--start 2023-01-01] \
  [--end 2025-12-31]
```

### `b1e55ed backtest gridsweep`

Sweep parameter combinations for a strategy.

```text
b1e55ed backtest gridsweep [--strategies momentum] [--assets BTC,ETH]
```

### `b1e55ed backtest megasweep`

Sweep all strategies × all parameter combos × all assets. Runs in parallel.

```text
b1e55ed backtest megasweep
```

### `b1e55ed backtest regime`

Regime-conditioned backtest results.

```text
b1e55ed backtest regime [--symbols BTC,ETH]
```

See: [backtest.md](backtest.md).

---

## System

### `b1e55ed health`

Cron-safe health check.

```text
b1e55ed health [--json]
```

### `b1e55ed status`

System status summary.

```text
b1e55ed status
```

### `b1e55ed integrity`

Verify hash chain integrity over the event store.

```text
b1e55ed integrity [--json]
```

### `b1e55ed replay`

Rebuild projections from the event log. Use after manual DB repair or to verify event store consistency.

```text
b1e55ed replay
```

---

## Identity and Keys

### `b1e55ed identity forge`

Forge a `0xb1e55ed`-prefixed Ethereum identity. Required for EAS attestations.

```text
b1e55ed identity forge [--threads N] [--json]
```

### `b1e55ed identity show`

Show the currently forged identity.

```text
b1e55ed identity show [--json]
```

### `b1e55ed keys list`

```text
b1e55ed keys list [--json]
```

### `b1e55ed keys set`

```text
b1e55ed keys set <name> <value> [--json]
```

### `b1e55ed keys remove`

```text
b1e55ed keys remove <name> [--json]
```

### `b1e55ed keys test`

```text
b1e55ed keys test [--json]
```

### `b1e55ed anchor`

Print the current hash-chain root. Optionally publish as an EAS attestation.

```text
b1e55ed anchor [--format json|text] [--eas]
```

### `b1e55ed export karma`

Export karma data from the event store.

```text
b1e55ed export karma \
  [--format jsonl|json|csv] \
  [--include-chain] \
  [--output <path>] \
  [--from DATE] \
  [--to DATE]
```

---

## Producers

### `b1e55ed producers register`

```text
b1e55ed producers register \
  --name <name> \
  --domain <domain> \
  --endpoint <url> \
  [--schedule "*/15 * * * *"]
```

### `b1e55ed producers list`

```text
b1e55ed producers list [--json]
```

### `b1e55ed producers remove`

```text
b1e55ed producers remove --name <name>
```

---

## Contributors

### `b1e55ed contributors register`

```text
b1e55ed contributors register \
  --name <name> \
  --role operator|agent|tester|curator \
  [--node-id <node_id>] \
  [--attest]
```

### `b1e55ed contributors list`

```text
b1e55ed contributors list [--json]
```

### `b1e55ed contributors remove`

```text
b1e55ed contributors remove --id <contributor_id>
```

### `b1e55ed contributors score`

```text
b1e55ed contributors score --id <contributor_id> [--json]
```

### `b1e55ed contributors leaderboard`

```text
b1e55ed contributors leaderboard [--limit N] [--json]
```

See: [contributors.md](contributors.md).

---

## Webhooks

Webhook subscriptions are stored in the local database.

### `b1e55ed webhooks add`

```text
b1e55ed webhooks add <url> --events "alert.*,system.kill_switch.*"
```

### `b1e55ed webhooks list`

```text
b1e55ed webhooks list [--json]
```

### `b1e55ed webhooks remove`

```text
b1e55ed webhooks remove <id>
```

---

## Services

### `b1e55ed api`

Start the REST API server.

```text
b1e55ed api [--host <host>] [--port <port>]
```

Default: `http://127.0.0.1:5050`

### `b1e55ed dashboard`

Start the dashboard.

```text
b1e55ed dashboard [--host <host>] [--port <port>]
```

Default: `http://127.0.0.1:5051`

---

## Integrations

### `b1e55ed eas status`

```text
b1e55ed eas status [--json]
```

### `b1e55ed eas verify`

```text
b1e55ed eas verify --uid <uid> [--json]
```

See: [eas-integration.md](eas-integration.md).

### `b1e55ed kill-switch`

Show current kill switch level.

```text
b1e55ed kill-switch [--json]
```

### `b1e55ed kill-switch set`

Set the kill switch level (0 = off, 1–4 = escalating restriction).

```text
b1e55ed kill-switch set <level 0-4> [--json]
```
