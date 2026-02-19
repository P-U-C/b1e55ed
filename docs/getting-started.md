# Getting Started

b1e55ed is an autonomous trading intelligence system that synthesizes multi-domain signals into conviction-weighted trading decisions.

## Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) package manager
- A master password for identity encryption

## Installation

### From wheel (recommended)

```bash
pip install b1e55ed-1.0.0-beta.1-py3-none-any.whl
```

### From source

```bash
git clone https://github.com/P-U-C/b1e55ed.git
cd b1e55ed
uv sync
```

## Quick Start

### 1. Initialize Identity

```bash
# Set master password
export B1E55ED_MASTER_PASSWORD="your-secure-password"

# Generate node identity (one-time)
uv run b1e55ed setup
```

This creates `~/.b1e55ed/identity.key` with your cryptographic identity.

### 2. Configure System

Edit `config/user.yaml` (or use defaults):

```yaml
preset: balanced  # conservative | balanced | degen | custom

# Symbol universe
universe:
  symbols: ["BTC", "ETH", "SOL", "SUI", "HYPE"]

# Domain weights (must sum to 1.0)
weights:
  curator: 0.25    # Human operator signals
  onchain: 0.25    # Blockchain data
  tradfi: 0.20     # CME, ETF flows
  social: 0.15     # Social intelligence
  technical: 0.10  # TA indicators
  events: 0.05     # Calendar events

# Risk limits
risk:
  max_drawdown_pct: 0.30        # 30% max portfolio drawdown
  max_daily_loss_usd: 240.0     # Daily loss limit
  max_position_size_pct: 0.15   # 15% max single position
  max_portfolio_heat_pct: 0.06  # 6% total capital at risk
```

See [configuration.md](configuration.md) for full options.

### 3. Run Your First Brain Cycle

```bash
# Paper trading mode (safe)
uv run b1e55ed brain

# This will:
# 1. Collect signals from all producers
# 2. Synthesize weighted conviction scores
# 3. Detect market regime
# 4. Generate trade intents
# 5. Run preflight checks
# 6. Execute via paper broker (no real money)
```

### 4. Start the Dashboard

```bash
# Terminal 1: API server
uv run b1e55ed api

# Terminal 2: Dashboard
uv run b1e55ed dashboard

# Open http://localhost:5051
```

## Key Concepts

### Brain Cycle (6 phases)

1. **Collection** - Producers generate signals
2. **Quality** - Data quality monitoring
3. **Synthesis** - Multi-domain weighted scoring
4. **Regime** - Market state detection (EARLY_BULL | BULL | CHOP | BEAR | CRISIS)
5. **Conviction** - PCS + counter-thesis scoring
6. **Decision** - Trade intent generation

### Producers (13 signal sources)

| Domain | Producers | Data Sources |
|--------|-----------|--------------|
| **Technical** | TA, Orderbook, Price Alerts | Exchange APIs |
| **On-chain** | On-chain, Stablecoin, Whale | Allium API |
| **TradFi** | TradFi, ETF | Binance, public data |
| **Social** | Social, Sentiment, ACI | TikTok, Fear & Greed |
| **Events** | Events | Economic calendar |
| **Curator** | Curator, Contract | Human operator |

### Execution Modes

- **Paper** - Simulated fills, no real money (default)
- **Live** - Real execution via Hyperliquid (requires funded account)

### Kill Switch (5 levels)

System auto-escalates risk protection based on conditions:

- **L0 NOMINAL** - Normal operation
- **L1 CAUTION** - Daily loss limit hit
- **L2 DEFENSIVE** - Portfolio heat exceeded
- **L3 LOCKDOWN** - Crisis regime detected
- **L4 EMERGENCY** - Max drawdown breached

## Next Steps

- [Configuration Guide](configuration.md) - Customize your setup
- [API Reference](api-reference.md) - REST API endpoints
- [Deployment](deployment.md) - Production hosting
- [Learning Loop](learning-loop.md) - How the system improves

## Troubleshooting

### Database locked
```bash
# Kill any running processes
pkill -f b1e55ed

# Or specify full database path
uv run b1e55ed brain --db /path/to/brain.db
```

### Identity errors
```bash
# Regenerate identity (WARNING: loses history)
rm ~/.b1e55ed/identity.key
uv run b1e55ed setup
```

### Import errors
```bash
# Fresh venv
rm -rf .venv
uv sync
```

## Support

- Issues: https://github.com/P-U-C/b1e55ed/issues
- Docs: [docs/](.)
- Tests: `uv run pytest tests/`
