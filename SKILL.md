# b1e55ed Operator Manual

b1e55ed is a CLI-first trading intelligence engine built around append-only events. Operators (humans or agents) control the system through shell commands and receive state as tables or JSON. The engine persists configuration, identity, keystore secrets, and a local event database so cycles are reproducible and auditable.

## Quick start

```bash
b1e55ed setup && b1e55ed keys test && b1e55ed brain
```

If you are running from source and `b1e55ed` is not on PATH:

```bash
uv sync
uv run b1e55ed setup && uv run b1e55ed keys test && uv run b1e55ed brain
```

## Commands (CLI reference)

Run `b1e55ed --help` for the authoritative list of commands available in your installed version.

### `b1e55ed setup`

Purpose: first-run configuration. Writes `config/user.yaml`, initializes the DB, ensures node identity exists, and stores secrets in the keystore when available.

Synopsis:

```bash
b1e55ed setup [--preset conservative|balanced|degen] [--non-interactive]
```

Behavior:
- Interactive by default.
- `--non-interactive` uses environment variables and skips prompts.

Key environment variables:
- `B1E55ED_MASTER_PASSWORD` (recommended): encrypts identity and keystore material at rest.
- `B1E55ED_PRESET`: default preset when non-interactive.
- `B1E55ED_NONINTERACTIVE`: set to `1|true|yes` to force non-interactive.

### `b1e55ed brain`

Purpose: run one brain cycle (collect → synthesize → decide). Intended to be safe by default when execution is configured as paper.

Synopsis:

```bash
b1e55ed brain
b1e55ed brain --full
b1e55ed brain --json
```

Notes:
- `--full` includes slow producers.
- `--json` emits a machine-readable result for operator automation.

### `b1e55ed signal`

Purpose: ingest operator intel as a curator signal event.

Synopsis:

```bash
b1e55ed signal "<text>"
b1e55ed signal add --file <path>
```

Operator guidance:
- Prefer a single compact signal containing context, tickers, timeframe, and rationale.
- Include links as plain text.

### `b1e55ed alerts`

Purpose: list active alerts (stops, targets, kill switch state, system warnings).

Synopsis:

```bash
b1e55ed alerts
b1e55ed alerts --json
b1e55ed alerts --watch
```

Notes:
- `--watch` is a blocking mode intended for terminals and long-running operator daemons.

### `b1e55ed positions`

Purpose: list open positions with PnL.

Synopsis:

```bash
b1e55ed positions
b1e55ed positions --json
```

### `b1e55ed kill-switch`

Purpose: inspect or override the system kill switch.

Synopsis:

```bash
b1e55ed kill-switch
b1e55ed kill-switch set <0-4>
```

Semantics (operator contract):
- `0`: normal
- `1`: caution
- `2`: risk-off
- `3`: stop execution
- `4`: emergency stop

### `b1e55ed keys`

Purpose: manage API keys and verify which producers are live.

Synopsis:

```bash
b1e55ed keys list
b1e55ed keys set <name> <value>
b1e55ed keys remove <name>
b1e55ed keys test [--json]
```

Conventions:
- Key names are dotted identifiers (example: `allium.api_key`).
- `keys list` must redact secrets.
- `keys test` should report per-provider status and coverage.

### `b1e55ed health`

Purpose: cron-safe health check.

Synopsis:

```bash
b1e55ed health
b1e55ed health --json
```

### `b1e55ed status`

Purpose: print local system status (config, DB, identity, keystore).

Synopsis:

```bash
b1e55ed status
b1e55ed status --json
```

### `b1e55ed api`

Purpose: start the FastAPI server.

Synopsis:

```bash
b1e55ed api [--host <host>] [--port <port>]
```

Default ports:
- API: `5050`

### `b1e55ed dashboard`

Purpose: start the web dashboard for passive monitoring.

Synopsis:

```bash
b1e55ed dashboard [--host <host>] [--port <port>]
b1e55ed dashboard --expose
```

Notes:
- Default dashboard port: `5051`.
- `--expose` binds to `0.0.0.0` and is intended for remote access with authentication.

## Keys and configuration

### Required

- `B1E55ED_MASTER_PASSWORD` is the required operator primitive for secure persistence. It encrypts the node identity (and any keystore secrets) at rest.
  - If missing, identity generation may fail unless you explicitly enable development mode.

### Common optional keys

These keys affect producer coverage. Missing keys should degrade capability but should not break a brain run.

- Hyperliquid execution
  - `hyperliquid.api_key`
  - `hyperliquid.api_secret`

- On-chain / enrichment
  - `allium.api_key`
  - `nansen.api_key`

- Social
  - `reddit.client_id`
  - `apify.token`

### How to set and verify keys

Recommended operator flow:

```bash
b1e55ed keys set allium.api_key "..."
b1e55ed keys set nansen.api_key "..."
b1e55ed keys test
```

For agent automation, prefer JSON:

```bash
b1e55ed keys test --json
```

## Dashboard (passive monitoring)

Use the dashboard for observation, not control. The CLI is the control plane.

Typical local workflow:

```bash
b1e55ed api
b1e55ed dashboard
# open http://localhost:5051
```

Operator expectation:
- Dashboard is read-oriented and safe to keep running.
- Alerts and positions must still be polled (or watched) by the operator layer.

## Heartbeat protocol (poll loop)

On each heartbeat (or scheduled poll), perform the following checks in order.

1. **Kill switch**
   - `b1e55ed kill-switch`
   - If level is `>= 3`, do not execute trades. Route an immediate operator message.

2. **Health**
   - `b1e55ed health --json`
   - If degraded, route an operator message with the failing subsystem.

3. **Alerts**
   - `b1e55ed alerts --json`
   - Route critical alerts immediately. Batch non-critical alerts.

4. **Positions**
   - `b1e55ed positions --json`
   - Detect stop/target proximity and anomalies (missing prices, stale marks).

5. **Brain cycle (optional depending on schedule)**
   - `b1e55ed brain` on the normal cadence.
   - `b1e55ed brain --full` on the slower cadence.

## Signal detection (operator intel ingestion)

Treat any of the following as a curator signal candidate:
- A message containing at least one ticker plus directional intent.
- A link to a chart/thread plus contextual commentary.
- Explicit `/signal` prefix.

Normalization rules:
- Preserve original text.
- Remove purely conversational filler.
- If multiple messages within 60 seconds appear to be part of one thought, concatenate in chronological order.

Ingestion:

```bash
b1e55ed signal "<normalized text>"
```

If the intel is multi-line or contains many links:

```bash
b1e55ed signal add --file /path/to/signal.txt
```

## Alert routing (operator delivery)

Severity mapping (operator contract):
- **Critical**: kill switch escalation, stop hit, target hit, execution failure.
  - Route immediately to the operator (chat, pager, webhook).
- **Standard**: new trade intent, significant conviction change, producer outage.
  - Route in the next summary batch (or immediately if the operator is active).
- **Low**: routine cycle completion, minor scoring changes.
  - Log only.

For automation, treat `b1e55ed alerts --json` as the source of truth and implement routing based on alert type and severity.

## Cron schedule (recommended)

Use these templates as a baseline. Adjust cadence to cost and latency constraints.

- Every 30 minutes: `b1e55ed brain`
- Every 6 hours: `b1e55ed brain --full`
- Every 5 minutes: `b1e55ed health`
- Daily summaries: `b1e55ed status --json`

Importable templates are provided at `config/crons.json`.
