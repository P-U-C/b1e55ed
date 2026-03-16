# CLI Reference

Authoritative source: `engine/cli/main.py` (`build_parser()`).

All commands support `--help`.

---

## Core

### `b1e55ed wizard`

Interactive 5-step onboarding for new contributors. Recommended first command after install.

```text
b1e55ed wizard
```

Covers: identity forge → config → producer registration → brain first run → API setup.
From source: `./b1e55ed wizard` or `uv run b1e55ed wizard`.

### `b1e55ed uninstall`

Removes b1e55ed from the system. Prompts for confirmation unless `--yes` is given.

```text
b1e55ed uninstall [--yes] [--keep-data]
```

| Flag | Description |
|---|---|
| `--yes` | Skip confirmation prompts |
| `--keep-data` | Preserve the data directory (brain DB, logs, config) |

Alternatively, run the standalone script: `./uninstall.sh`.

### `b1e55ed setup`

Low-level setup. Writes `config/user.yaml`, initializes `data/brain.db`. The wizard calls this internally.

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

### `b1e55ed report`

Generate flywheel reports.

```text
b1e55ed report --stratification [--json]
b1e55ed report --cockpit-summary [--json]
```

| Flag | Description |
|---|---|
| `--stratification` | Confidence stratification report — compares high-confidence (≥0.65) vs low-confidence (<0.45) signal outcomes over 30 days |
| `--cockpit-summary` | 7-day cockpit summary — top convictions, regime, kill switch state, recent P&L |
| `--json` | Machine-readable JSON output |

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

### `b1e55ed identity restore`

Recover a lost identity from an Ethereum private key. The Ed25519 signing key is deterministically derived via HKDF — no backup file needed.

```text
b1e55ed identity restore --eth-key <hex-private-key>
```

See [Identity recovery](identity.md) for the full procedure.

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

### `b1e55ed daemon`

Start all subsystems as a supervised process group. **Recommended for production** — manages API, dashboard, brain cycles, and outcome resolution with automatic restart.

```text
b1e55ed daemon [--status]
```

- `--status` — show daemon status and exit without starting

### `b1e55ed start`

Start API + dashboard together. **Recommended entry point** — opens browser automatically.

```text
b1e55ed start [--api-port <port>] [--dashboard-port <port>] [--host <host>] [--no-browser]
```

Defaults: API on `5050`, dashboard on `5051`, host `127.0.0.1`. Press `Ctrl+C` to stop both.

### `b1e55ed api`

Start the REST API server (standalone).

```text
b1e55ed api [--host <host>] [--port <port>]
```

Default: `http://127.0.0.1:5050`

### `b1e55ed dashboard`

Start the dashboard (standalone).

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

### `b1e55ed resolve-outcomes`

Resolve elapsed `FORECAST_V1` events against actual prices. Writes `FORECAST_OUTCOME_V1` events (immutable). Idempotent — safe to run every 30 minutes via cron.

```text
b1e55ed resolve-outcomes
```

Returns: count of forecasts resolved in this run. Exit 0 always.

### `b1e55ed prune`

Prune old data records according to the retention policy defined in `config/user.yaml`.

```text
b1e55ed prune [--dry-run] [--events-days N] [--json]
```

- `--dry-run` — show row counts that *would* be deleted without actually deleting
- `--events-days N` — override `retention.events_keep_days` for this run
- `--json` — machine-readable JSON output

Returns: counts of deleted (or would-delete) rows per table. Runs `VACUUM` after deletion if configured.

---

### `b1e55ed verify-chain`

Run a full hash-chain integrity verification across all events in the event store. Unlike the dashboard fast-verify (which checks only recent events), this scans the complete event log.

```text
b1e55ed verify-chain [--json]
```

- `--json` — machine-readable JSON output

Returns: `PASS` or `FAIL` with event count and first failing event ID if integrity is broken.

---

### `b1e55ed reconcile`

Scan all positions and orders for missing provenance events and backfill them idempotently. Safe to run multiple times. Runs automatically at daemon startup.

```text
b1e55ed reconcile [--json]
```

- `--json` — machine-readable JSON output

Returns: counts of backfilled events per type. Backfilled `SIGNAL_ACCEPTED_V1` events carry `recovery_placeholder=true` to distinguish them from real attribution events.


---

## spi

Manage SPI (Standard Producer Interface) signal producers.

### `b1e55ed spi register`

Register a new external signal producer interactively.

```text
b1e55ed spi register
```

Prompts for producer ID, name, ingress mode, and API URL (adapter mode only). Saves producer config to `~/.b1e55ed/spi/producers/{id}.json`. The API key is displayed once — store it securely.

### `b1e55ed spi status`

List all registered producers and their lifecycle states.

```text
b1e55ed spi status
```

Displays: producer_id | state | ingress | karma | resolved

### `b1e55ed spi promote`

Manually advance a producer's lifecycle state.

```text
b1e55ed spi promote <producer_id>
```

### `b1e55ed spi test-key`

Validate an API key for a registered producer.

```text
b1e55ed spi test-key <producer_id>
```

Prompts for the API key and tests it against the running API server.
