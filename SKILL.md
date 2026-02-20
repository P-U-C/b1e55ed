# b1e55ed Operator Manual

b1e55ed is a CLI-first trading intelligence engine built around append-only events.

Operators control the system via shell commands and receive state as tables or JSON.

## Quick start

Recommended first run:

```bash
b1e55ed identity forge && b1e55ed setup && b1e55ed keys test && b1e55ed contributors register --name "local-operator" --role operator && b1e55ed brain
```

If you are running from source:

```bash
uv sync
uv run b1e55ed identity forge
uv run b1e55ed setup
uv run b1e55ed keys test
uv run b1e55ed contributors register --name "local-operator" --role operator
uv run b1e55ed brain
```

## Command index

- Setup: `setup`
- Brain: `brain`
- Signals: `signal`
- Positions: `positions`
- Producers: `producers register|list|remove`
- Contributors: `contributors list|register|remove|score|leaderboard`
- Identity: `identity forge|show`
- Webhooks: `webhooks add|list|remove`
- Alerts: `alerts`
- Kill switch: `kill-switch`, `kill-switch set`
- Health: `health`
- Keys: `keys list|set|remove|test`
- EAS: `eas status|verify`
- Servers: `api`, `dashboard`
- Status: `status`

Run `b1e55ed --help` for the authoritative list.

## Identity

### `b1e55ed identity forge|show`

The Forge derives an Ethereum identity with a `0xb1e55ed` prefix.

```bash
b1e55ed identity forge
b1e55ed identity show
```

Outputs are written under `.b1e55ed/` in the repo.

## Contributors

Contributors are the attribution unit for signals.

```bash
b1e55ed contributors list
b1e55ed contributors register --name "alice" --role operator
b1e55ed contributors remove --id <contributor_id>

b1e55ed contributors score --id <contributor_id>
b1e55ed contributors leaderboard --limit 20
```

If EAS is enabled and configured:

```bash
b1e55ed contributors register --name "alice" --role operator --attest
```

## Producers

Dynamic producers can be recorded in the local database.

```bash
b1e55ed producers register --name example --domain onchain --endpoint https://example.internal/poll
b1e55ed producers list
b1e55ed producers remove --name example
```

## Webhooks

Webhook subscriptions are stored in the database and matched against event types via glob patterns.

```bash
b1e55ed webhooks add https://example.internal/webhook --events "alert.*,system.kill_switch.*"
b1e55ed webhooks list
b1e55ed webhooks remove 1
```

## EAS

EAS utilities for configuration visibility and local verification.

```bash
b1e55ed eas status
b1e55ed eas verify --uid <uid>
```

## Brain

```bash
b1e55ed brain
b1e55ed brain --full
b1e55ed brain --json
```

## Signals

```bash
b1e55ed signal "BTC bullish on flows" --direction bullish --conviction 7
b1e55ed signal add --file ./note.txt
```

## Alerts

```bash
b1e55ed alerts
b1e55ed alerts --since 60 --json
```

## Kill switch

```bash
b1e55ed kill-switch
b1e55ed kill-switch set 3
```

## Health and status

```bash
b1e55ed health
b1e55ed status
```

## Keys

```bash
b1e55ed keys list
b1e55ed keys set allium.api_key "..."
b1e55ed keys test
```
