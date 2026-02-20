# Configuration

b1e55ed is configured via YAML and environment variables.

## Configuration surfaces

1. `config/default.yaml` (repo defaults)
2. `config/presets/*.yaml` (preset overlay)
3. `config/user.yaml` (operator overlay)
4. Environment variables (`B1E55ED_*`) for overrides and secrets

Later surfaces override earlier ones.

## Environment variable mapping

The config model uses:

- Prefix: `B1E55ED_`
- Nested delimiter: `__`

Examples:

```bash
export B1E55ED_API__AUTH_TOKEN="..."
export B1E55ED_EXECUTION__MODE="paper"
export B1E55ED_EAS__ENABLED="true"
```

## Core sections

### `weights`

Synthesis domain weights. Must sum to `1.0` (±0.001).

```yaml
weights:
  curator: 0.25
  onchain: 0.25
  tradfi: 0.20
  social: 0.15
  technical: 0.10
  events: 0.05
```

### `risk`

```yaml
risk:
  max_leverage: 2.0
  max_position_pct: 0.10
  max_portfolio_heat_pct: 0.06
  daily_loss_limit_pct: 0.03
  max_drawdown_pct: 0.30
```

### `brain`

```yaml
brain:
  cycle_interval_seconds: 1800
```

### `execution`

```yaml
execution:
  mode: paper                 # paper|live
  paper_start_balance: 10000
  confirmation_threshold_usd: 500
  paper_min_days: 14
```

### `kill_switch`

```yaml
kill_switch:
  l1_daily_loss_pct: 0.03
  l2_portfolio_heat_pct: 0.06
  l3_crisis_threshold: 2
  l4_max_drawdown_pct: 0.30
```

### `karma`

```yaml
karma:
  enabled: true
  percentage: 0.005
  settlement_mode: manual     # manual|daily|weekly|threshold
  threshold_usd: 50
  treasury_address: "0x..."
```

### `universe`

```yaml
universe:
  symbols: ["BTC", "ETH", "SOL", "SUI", "HYPE"]
  max_size: 100
```

### `api`

```yaml
api:
  host: "127.0.0.1"
  port: 5050
  auth_token: ""             # required unless B1E55ED_INSECURE_OK=1
```

### `dashboard`

```yaml
dashboard:
  host: "127.0.0.1"
  port: 5051
  auth_token: ""             # optional in this version
```

### `eas` (Ethereum Attestation Service)

EAS is optional and disabled by default.

```yaml
eas:
  enabled: false
  rpc_url: "https://eth.llamarpc.com"
  eas_contract: "0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587"
  schema_registry: "0xA7b39296258348C78294F95B872b282326A97BDF"
  schema_uid: ""               # set after schema registration
  attester_private_key: ""     # required for creating attestations
  mode: offchain               # onchain|offchain
```

Related commands:
- `b1e55ed eas status`
- `b1e55ed eas verify --uid <uid>`

See: [eas-integration.md](eas-integration.md).

## Webhooks

Webhook subscriptions are stored in the database and managed via the CLI:

- `b1e55ed webhooks add <url> --events "alert.*,system.kill_switch.*"`
- `b1e55ed webhooks list`
- `b1e55ed webhooks remove <id>`

There is no YAML configuration block for webhooks in this version.

## Schema reference

Authoritative model: `engine/core/config.py`.
