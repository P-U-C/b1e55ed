# b1e55ed

<p align="center">
  <img src="assets/b1e55ed-hero.jpg" alt="b1e55ed" width="900" />
</p>

**b1e55ed** (0xb1e55ed = "blessed") — A sovereign trading intelligence system with compound learning.

Not a mechanism — an organism. It learns from every trade, every signal, every mistake. Its conviction weights shift. Its producer scores evolve. Its corpus grows. The system you deploy today is not the system running six months from now.

Built around one primitive: **events**. Producers emit events. The brain reads events and emits events. Execution reads events and emits events. An append-only hash chain makes the whole thing auditable by construction.

[![Tests](https://github.com/P-U-C/b1e55ed/workflows/CI/badge.svg)](https://github.com/P-U-C/b1e55ed/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Features

- **13 Signal Producers** - Technical, on-chain, TradFi, social intelligence
- **6-Phase Brain** - Collection → Quality → Synthesis → Regime → Conviction → Decision
- **Kill Switch** - 5 escalation levels, auto-triggered risk protection
- **Learning Loop** - Domain weights auto-adjust based on performance
- **Paper + Live Trading** - Hyperliquid execution with preflight checks
- **Karma Engine** - Optional 0.5% profit-sharing on realized gains
- **REST API** - 12 routes for monitoring and control
- **Web Dashboard** - Real-time intelligence UI (HTMX + Jinja2)

## Installation

### Option 1: Docker (Recommended)

**Quickest way to evaluate:**

```bash
# 1. Clone repository
git clone https://github.com/P-U-C/b1e55ed.git
cd b1e55ed

# 2. Configure environment
cp .env.template .env
vim .env  # Set B1E55ED_MASTER_PASSWORD at minimum

# 3. Start all services
docker-compose up -d

# 4. Access
# API:       http://localhost:5050/health
# Dashboard: http://localhost:5051
```

**Includes:**
- API server (port 5050)
- Dashboard (port 5051)
- Brain cycle (every 5 min)
- Persistent volumes for data/logs

**Stop:**
```bash
docker-compose down
```

### Option 2: Automated Install Script

**One-command deployment on Ubuntu/Debian:**

```bash
curl -fsSL https://raw.githubusercontent.com/P-U-C/b1e55ed/main/scripts/install.sh | sudo bash
```

This will:
- Install dependencies (Python 3.12, uv, SQLite)
- Create service user
- Setup systemd services
- Generate identity
- Configure log rotation
- Start API + Dashboard + Brain

**Post-install:**
```bash
# Check status
sudo systemctl status b1e55ed-api
sudo systemctl status b1e55ed-dashboard

# View logs
sudo journalctl -u b1e55ed-api -f
tail -f /var/log/b1e55ed/brain.log

# Access
curl http://localhost:5050/health
```

### Option 3: Manual Installation

**From wheel (Python 3.11+):**

```bash
# 1. Download release
wget https://github.com/P-U-C/b1e55ed/releases/download/v1.0.0-beta.1/b1e55ed-1.0.0b1-py3-none-any.whl

# 2. Install
pip install b1e55ed-1.0.0b1-py3-none-any.whl

# 3. Generate identity
export B1E55ED_MASTER_PASSWORD="your-secure-password"
b1e55ed setup

# 4. Run
b1e55ed brain  # Single cycle
b1e55ed api    # Start API
b1e55ed dashboard  # Start dashboard
```

**From source:**

```bash
# 1. Clone
git clone https://github.com/P-U-C/b1e55ed.git
cd b1e55ed

# 2. Install uv
curl -fsSL https://astral.sh/uv/install.sh | sh

# 3. Install dependencies
uv sync

# 4. Run tests
uv run pytest tests/ -v

# 5. Generate identity
export B1E55ED_MASTER_PASSWORD="your-password"
uv run b1e55ed setup

# 6. Run
uv run b1e55ed brain
```

## Quick Start

### 1. Configure

Edit `config/user.yaml` or use environment variables:

```yaml
preset: balanced  # conservative | balanced | degen

universe:
  symbols: ["BTC", "ETH", "SOL", "SUI", "HYPE"]

weights:
  curator: 0.25   # Human operator signals
  onchain: 0.25   # Blockchain data
  tradfi: 0.20    # CME, ETF flows
  social: 0.15    # Social intelligence
  technical: 0.10 # TA indicators
  events: 0.05    # Calendar events

execution:
  mode: paper  # paper | live
```

### 2. Run Brain Cycle

```bash
# Paper trading (safe)
b1e55ed brain

# This will:
# 1. Collect signals from all producers
# 2. Synthesize weighted conviction scores
# 3. Detect market regime
# 4. Generate trade intents
# 5. Execute via paper broker
```

### 3. Access Dashboard

```bash
# Terminal 1: API
b1e55ed api

# Terminal 2: Dashboard
b1e55ed dashboard

# Open http://localhost:5051
```

See **[Getting Started Guide](docs/getting-started.md)** for detailed setup.

## Documentation

- [Getting Started](docs/getting-started.md) - Setup, concepts, troubleshooting
- [Configuration](docs/configuration.md) - Presets, weights, risk settings
- [API Reference](docs/api-reference.md) - REST endpoints, examples
- [Deployment](docs/deployment.md) - Production hosting, security
- [Learning Loop](docs/learning-loop.md) - How weights auto-adjust

## Architecture

### Event-Sourced Core

```
Producers → Events → Database (hash chain) → Brain → Conviction → Execution → Events
                          ↑                                              ↓
                          └──────────────────────────────────────────────┘
```

Everything is an event. Producers don't push to the brain — they write events. The brain doesn't call producers — it reads events. The hash chain makes every decision auditable.

### Brain Cycle (6 Phases)

1. **Collection** - Gather signals from 13 producers
2. **Quality** - Monitor data freshness and staleness
3. **Synthesis** - Multi-domain weighted scoring (PCS)
4. **Regime** - Detect market state (EARLY_BULL | BULL | CHOP | BEAR | CRISIS)
5. **Conviction** - PCS + counter-thesis scoring (CTS)
6. **Decision** - Generate trade intents with sizing

### Producers (13 Signal Sources)

| Domain | Producers | Data |
|--------|-----------|------|
| **Technical** | TA, Orderbook, Price Alerts | RSI, MACD, volume, levels |
| **On-chain** | On-chain, Stablecoin, Whale | Flows, wallets, cluster tracking |
| **TradFi** | TradFi, ETF | CME basis, funding, ETF flows |
| **Social** | Social, Sentiment, ACI | TikTok, Fear & Greed, CT intel |
| **Events** | Events | Economic calendar |
| **Curator** | Curator, Contract | Human operator signals |

### Kill Switch (5 Levels)

Auto-escalating risk protection:

- **L0 NOMINAL** - Normal operation
- **L1 CAUTION** - Daily loss limit hit (-3%)
- **L2 DEFENSIVE** - Portfolio heat exceeded (6%)
- **L3 LOCKDOWN** - Crisis regime detected
- **L4 EMERGENCY** - Max drawdown breached (-30%)

System **cannot de-escalate automatically** — only operator override.

### Learning Loop

Domain weights auto-adjust monthly based on realized P&L attribution:

```python
# Correlation: domain performance → profit
if domain_score_high and trade_profitable:
    increase_weight(domain)

# Bounded: 5% floor, 40% ceiling, max ±2% delta per cycle
```

## Development

### Tests

```bash
# All tests (150+)
uv run pytest tests/ -v

# Coverage
uv run pytest tests/ --cov=engine --cov-report=html

# Specific
uv run pytest tests/unit/test_conviction.py -v
```

### Lint & Type Check

```bash
# Lint
uv run ruff check .
uv run ruff format .

# Type check
uv run mypy engine/
```

### CI/CD

6 jobs on every push/PR:
- **test** - 150 unit/integration tests
- **lint** - ruff check + format
- **typecheck** - mypy strict
- **smoke** - CLI, imports, DB, config
- **security** - bandit + safety + secrets
- **build** - wheel + sdist + install verification

## Design Principles

1. **Event contract is the primitive** - Everything flows through events
2. **Three config surfaces max** - `default.yaml`, `presets/*.yaml`, env vars (secrets only)
3. **One kill switch, five levels** - Auto-escalate only, never de-escalate
4. **Paper before live** - Test everything in paper mode first
5. **Bounded adaptation** - Learning loop has floors, ceilings, max deltas

## Project Structure

```
b1e55ed/
├── engine/           # Core system
│   ├── brain/        # Orchestrator, conviction, regime
│   ├── core/         # Events, database, config, policy
│   ├── execution/    # OMS, paper broker, Hyperliquid
│   ├── producers/    # 13 signal producers
│   ├── security/     # Identity, keystore, audit
│   └── integration/  # Learning loop, hooks
├── api/              # REST API (FastAPI)
├── dashboard/        # Web UI (HTMX + Jinja2)
├── config/           # Defaults + presets
├── tests/            # 150+ tests
├── docs/             # Documentation
└── scripts/          # Install script, utilities
```

## Karma

> "We make a living by what we get. We make a life by what we give." — Winston Churchill

Optional profit-sharing mechanism (default: disabled).

When enabled (via `karma.enabled = true`), the system:
1. Tracks realized profit on each trade
2. Creates a signed intent for 0.5% of profit
3. Batches and settles to configured treasury address

**Configurable:**
```yaml
karma:
  enabled: false           # Opt-in
  percentage: 0.005        # 0.5% of profit
  treasury_address: "0x..."
  settlement_mode: manual  # manual | daily | threshold
```

No impact on losses. Only applied to realized gains.

## License

MIT

---

**Status:** v1.0.0-beta.1 (Feature-complete, paper trading validated, not yet battle-tested with real capital)

**Support:** [Issues](https://github.com/P-U-C/b1e55ed/issues) | [Discussions](https://github.com/P-U-C/b1e55ed/discussions)
