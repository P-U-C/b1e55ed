# Configuration

b1e55ed is configured via YAML files and environment variables. The system follows a preset → override pattern.

## Configuration Hierarchy

1. **Defaults** - `config/default.yaml` (shipped with package)
2. **Presets** - `config/presets/{preset}.yaml` (conservative/balanced/degen)
3. **User overrides** - `config/user.yaml` (your customizations)
4. **Environment variables** - `B1E55ED_*` (secrets, runtime overrides)

Later sources override earlier ones.

## Quick Start

```bash
# Copy default to start
cp config/default.yaml config/user.yaml

# Edit your settings
vim config/user.yaml
```

## Presets

Choose a risk profile:

### Conservative
```yaml
preset: conservative

risk:
  max_drawdown_pct: 0.15        # 15% max drawdown
  max_daily_loss_usd: 120.0     # Conservative loss limit
  max_position_size_pct: 0.10   # 10% max position
  max_leverage_bull: 1.0        # No leverage
```

### Balanced (default)
```yaml
preset: balanced

risk:
  max_drawdown_pct: 0.30        # 30% max drawdown
  max_daily_loss_usd: 240.0     # Moderate loss limit
  max_position_size_pct: 0.15   # 15% max position
  max_leverage_bull: 3.0        # 3x max in bull regime
```

### Degen
```yaml
preset: degen

risk:
  max_drawdown_pct: 0.50        # 50% max drawdown
  max_daily_loss_usd: 500.0     # Aggressive loss limit
  max_position_size_pct: 0.25   # 25% max position
  max_leverage_bull: 5.0        # 5x max in bull regime
```

## Configuration Sections

### Universe

Define which assets to trade:

```yaml
universe:
  symbols: ["BTC", "ETH", "SOL", "SUI", "HYPE"]
  max_size: 100  # Max symbols to monitor
```

### Domain Weights

How much to trust each signal source (must sum to 1.0):

```yaml
weights:
  curator: 0.25    # Human operator signals
  onchain: 0.25    # Blockchain analytics
  tradfi: 0.20     # TradFi flows (CME, ETF)
  social: 0.15     # Social intelligence
  technical: 0.10  # Technical analysis
  events: 0.05     # Event calendar

# Learning loop auto-adjusts these based on performance
```

### Risk Management

```yaml
risk:
  # Portfolio-level limits
  max_drawdown_pct: 0.30           # Emergency shutdown at -30%
  max_daily_loss_usd: 240.0        # Daily loss limit
  max_portfolio_heat_pct: 0.06     # 6% total capital at risk
  
  # Position-level limits
  max_position_size_pct: 0.15      # 15% max single position
  
  # Leverage by regime
  max_leverage_bull: 3.0           # Bull market
  max_leverage_early_bull: 2.0     # Early bull
  max_leverage_chop: 1.0           # Choppy/sideways
  max_leverage_bear: 0.0           # Bear (spot only)
```

### Brain

```yaml
brain:
  cycle_interval_s: 300            # Brain runs every 5 min
  conviction_threshold: 0.7        # Min conviction to trade (0-1)
  counter_thesis_trigger: 0.75     # PCS level that activates devil's advocate
```

### Execution

```yaml
execution:
  mode: paper                      # paper | live
  default_platform: hyperliquid
  slippage_tolerance_bps: 10       # 0.1% slippage tolerance
  
  # Order type preferences
  market_order_max_usd: 1000       # Use market orders below $1K
  limit_order_offset_bps: 5        # 0.05% better than mid for limits
```

### Kill Switch

```yaml
kill_switch:
  enabled: true
  
  # Auto-escalation triggers
  l1_daily_loss_pct: 0.03          # Caution at -3% daily
  l2_portfolio_heat_pct: 0.06      # Defensive at 6% heat
  l3_crisis_threshold: 0.8         # Lockdown if crisis score >0.8
  l4_max_drawdown_pct: 0.30        # Emergency at -30% total
```

### Karma

Optional profit-sharing mechanism:

```yaml
karma:
  enabled: false                   # Opt-in
  percentage: 0.005                # 0.5% of profit
  treasury_address: "0x..."        # Destination wallet
  settlement_mode: manual          # manual | daily | threshold
  threshold_usd: 50.0              # Auto-settle above $50
```

### API

```yaml
api:
  host: "127.0.0.1"
  port: 5050
  auth_token: ""                   # Bearer token (or env var)
```

### Dashboard

```yaml
dashboard:
  host: "127.0.0.1"
  port: 5051
  auth_token: ""                   # Optional basic auth
```

### Logging

```yaml
logging:
  level: INFO                      # DEBUG | INFO | WARNING | ERROR
  json_output: false               # JSON logs for production
```

## Environment Variables

Secrets and runtime overrides via env vars:

```bash
# Identity encryption
export B1E55ED_MASTER_PASSWORD="your-secure-password"

# API tokens (producers)
export B1E55ED_ALLIUM_API_KEY="..."
export B1E55ED_NANSEN_API_KEY="..."

# Execution credentials
export B1E55ED_HYPERLIQUID_API_KEY="..."
export B1E55ED_HYPERLIQUID_SECRET="..."

# API auth
export B1E55ED_API__AUTH_TOKEN="bearer-token-here"

# Override any config value
export B1E55ED_EXECUTION__MODE="live"
export B1E55ED_RISK__MAX_DRAWDOWN_PCT="0.15"
```

**Naming convention:** `B1E55ED_<SECTION>__<KEY>=<value>`

Nested config: double underscore `__` separates levels.

## Custom Preset

Create your own preset:

```yaml
# config/presets/my-preset.yaml
weights:
  curator: 0.30
  onchain: 0.30
  tradfi: 0.20
  social: 0.10
  technical: 0.05
  events: 0.05

risk:
  max_drawdown_pct: 0.20
  max_daily_loss_usd: 150.0
  max_position_size_pct: 0.12
  max_leverage_bull: 2.5
```

Then use it:

```yaml
# config/user.yaml
preset: my-preset
```

## Validation

Config is validated on load. Common errors:

### Weights don't sum to 1.0
```
ConfigError: Domain weights must sum to 1.0 (got 0.95)
```

**Fix:** Adjust weights to sum exactly to 1.0.

### Invalid regime
```
ConfigError: Unknown preset 'agressive' (valid: conservative, balanced, degen, custom)
```

**Fix:** Check spelling or use `custom` with manual config.

### Missing required field
```
ConfigError: execution.default_platform is required
```

**Fix:** Add the missing field to your config.

## Best Practices

1. **Start with a preset** - Modify from there
2. **Use environment variables for secrets** - Never commit API keys
3. **Test changes with paper mode** - Verify before going live
4. **Version your config** - Track changes in git
5. **Review after updates** - Schema may change between versions

## Advanced: Programmatic Config

```python
from engine.core.config import Config

# Load from file
config = Config.from_yaml("config/user.yaml")

# Override in code
config.execution.mode = "paper"
config.risk.max_drawdown_pct = 0.15

# Access nested values
assert config.weights.curator == 0.25
```

## Schema Reference

Full schema with types and constraints:

```python
# See engine/core/config.py for complete Pydantic models
class Config(BaseSettings):
    preset: Literal["conservative", "balanced", "degen", "custom"]
    weights: DomainWeights
    risk: RiskConfig
    brain: BrainConfig
    execution: ExecutionConfig
    kill_switch: KillSwitchConfig
    karma: KarmaConfig
    universe: UniverseConfig
    logging: LoggingConfig
    api: ApiConfig
    dashboard: DashboardConfig
```

## Next Steps

- [Getting Started](getting-started.md) - Basic setup
- [Deployment](deployment.md) - Production config
- [API Reference](api-reference.md) - REST API config
