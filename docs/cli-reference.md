# CLI Reference

Authoritative source: `engine/cli.py` (`build_parser()`).

All commands support `--help`.

## Setup

### `b1e55ed setup`

Interactive onboarding.

```text
b1e55ed setup [--preset conservative|balanced|degen] [--non-interactive]
```

Notes:
- Writes `config/user.yaml`.
- Initializes `data/brain.db`.

## Identity

### `b1e55ed identity forge`

Forge a `0xb1e55ed`-prefixed Ethereum identity.

```text
b1e55ed identity forge [--threads N] [--json]
```

### `b1e55ed identity show`

Show the currently forged identity.

```text
b1e55ed identity show [--json]
```

## Brain

### `b1e55ed brain`

Run one brain cycle.

```text
b1e55ed brain [--full] [--json]
```

## Signals

### `b1e55ed signal`

Ingest operator intel as a curator signal.

```text
b1e55ed signal "<text>" [--symbols "BTC,ETH"] [--source "operator"] [--direction bullish|bearish|neutral] [--conviction 0-10] [--json]

b1e55ed signal add --file <path> [--symbols ...] [--source ...] [--direction ...] [--conviction ...] [--json]
```

## Positions

### `b1e55ed positions`

List open positions with best-effort mark price PnL.

```text
b1e55ed positions [--json]
```

## Producers

### `b1e55ed producers register`

```text
b1e55ed producers register --name <name> --domain <domain> --endpoint <url> [--schedule "*/15 * * * *"]
```

### `b1e55ed producers list`

```text
b1e55ed producers list [--json]
```

### `b1e55ed producers remove`

```text
b1e55ed producers remove --name <name>
```

## Contributors

### `b1e55ed contributors list`

```text
b1e55ed contributors list [--json]
```

### `b1e55ed contributors register`

```text
b1e55ed contributors register --name <name> --role operator|agent|tester|curator [--node-id <node_id>] [--attest]
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

## Alerts

### `b1e55ed alerts`

```text
b1e55ed alerts [--since <minutes>] [--json]
```

## Kill switch

### `b1e55ed kill-switch`

```text
b1e55ed kill-switch [--json]
```

### `b1e55ed kill-switch set`

```text
b1e55ed kill-switch set <level 0-4> [--json]
```

## Health

### `b1e55ed health`

Cron-safe health check.

```text
b1e55ed health [--json]
```

## Keys

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

## EAS

### `b1e55ed eas status`

```text
b1e55ed eas status [--json]
```

### `b1e55ed eas verify`

```text
b1e55ed eas verify --uid <uid> [--json]
```

## API

### `b1e55ed api`

```text
b1e55ed api [--host <host>] [--port <port>]
```

## Dashboard

### `b1e55ed dashboard`

```text
b1e55ed dashboard [--host <host>] [--port <port>]
```

## Status

### `b1e55ed status`

```text
b1e55ed status
```
