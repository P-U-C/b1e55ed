# b1e55ed

<p align="center">
  <img src="assets/b1e55ed-hero.jpg" alt="b1e55ed" width="900" />
</p>

**b1e55ed** (0xb1e55ed = "blessed") — a sovereign trading intelligence system with compound learning.

Built around one primitive: **events**. Producers emit events. The brain reads events and emits events. Execution reads events and emits events. An append-only hash chain makes the system auditable by construction.

**v1.0.0-beta.2** — Operator Layer + Contributor Network

[![Tests](https://github.com/P-U-C/b1e55ed/workflows/CI/badge.svg)](https://github.com/P-U-C/b1e55ed/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Features

- **Event-sourced core** — append-only DB + hash chain, every decision auditable
- **Brain engine** — 6-phase cycle: collection → quality → synthesis → regime → conviction → decision
- **13 signal producers** across 6 domains (technical, on-chain, TradFi, social, events, curator)
- **CLI control plane** — 16 commands, tables or `--json` for machine consumption
- **REST API** — 24 endpoints under `/api/v1/`, OpenAPI spec at `/docs`
- **Dashboard** — 12 pages, HTMX + Jinja2, CRT aesthetic
- **Kill switch** — 5 levels, auto-escalate, operator-only de-escalate
- **Learning loop** — domain weight auto-adjustment with bounded adaptation
- **Dynamic producer registration** — agents add signal sources at runtime
- **Contributor network** — registry, signal attribution, reputation scoring, leaderboard
- **The Forge** — vanity `0xb1e55ed` identity derivation (Rust + Python grinder)
- **EAS integration** — Ethereum Attestation Service for contributor registry (Ethereum mainnet)
- **Identity gate** — no forge, no access
- **Webhook dispatch** — event subscriptions with retry + backoff
- **Karma / treasury** — profit-sharing with cryptographic receipts
- **Structured errors** — consistent `{"error": {"code", "message"}}` across API
- **225 tests** — strict CI (lint, types, smoke, security, brand, docs, build)

## Quick Start

```bash
git clone https://github.com/P-U-C/b1e55ed.git
cd b1e55ed
uv sync
```

Sequence: **forge identity → setup → register → brain**.

```bash
export B1E55ED_MASTER_PASSWORD="your-secure-password"

# 1. Forge your 0xb1e55ed identity (one-time, takes a few minutes)
uv run b1e55ed identity forge

# 2. Configure the engine
uv run b1e55ed setup

# 3. Register as a contributor
uv run b1e55ed contributors register --name "my-handle" --role operator

# 4. Run the brain
uv run b1e55ed brain
```

Start API + dashboard:

```bash
export B1E55ED_API__AUTH_TOKEN="your-secret-token"
uv run b1e55ed api         # http://localhost:5050/api/v1/health
uv run b1e55ed dashboard   # http://localhost:5051
```

See [Getting Started](docs/getting-started.md) for detailed setup.

## Architecture

### Event-Sourced Core

```
Producers → Events → Database (hash chain) → Brain → Conviction → Execution → Events
                          ↑                                              ↓
                          └──────────────────────────────────────────────┘
```

Everything is an event. Producers don't push to the brain — they write events. The brain doesn't call producers — it reads events. The hash chain makes every decision auditable.

### Brain Cycle (6 Phases)

1. **Collection** — gather signals from 13 producers
2. **Quality** — monitor data freshness and staleness
3. **Synthesis** — multi-domain weighted scoring (PCS)
4. **Regime** — detect market state (EARLY_BULL | BULL | CHOP | BEAR | CRISIS)
5. **Conviction** — PCS + counter-thesis scoring (CTS)
6. **Decision** — generate trade intents with sizing

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

- **L0 NOMINAL** — normal operation
- **L1 CAUTION** — daily loss limit hit (-3%)
- **L2 DEFENSIVE** — portfolio heat exceeded (6%)
- **L3 LOCKDOWN** — crisis regime detected
- **L4 EMERGENCY** — max drawdown breached (-30%)

System **cannot de-escalate automatically** — only operator override.

### Learning Loop

Domain weights auto-adjust monthly based on realized P&L attribution:

```python
if domain_score_high and trade_profitable:
    increase_weight(domain)

# Bounded: 5% floor, 40% ceiling, max ±2% delta per cycle
```

## The Forge

Every b1e55ed identity begins with `0xb1e55ed`. The address is derived through computational work — a vanity grinder that searches for an Ethereum keypair with the prefix.

```bash
uv run b1e55ed identity forge
```

The work is the point. No forge, no access.

Docs: [docs/FORGE_SPEC.md](docs/FORGE_SPEC.md)

## Contributor Network

Contributors are first-class entities — operators, agents, testers, curators. Every signal is attributed. Reputation compounds.

```bash
uv run b1e55ed contributors register --name "my-handle" --role tester --attest
uv run b1e55ed contributors leaderboard
```

- **Signal attribution** — every signal tracks who submitted it
- **Reputation scoring** — composite score from hit rate, volume, consistency, conviction accuracy
- **EAS attestations** — optional, on Ethereum mainnet (`0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587`)
- **Leaderboard** — API + CLI

Docs: [docs/contributors.md](docs/contributors.md) · [docs/eas-integration.md](docs/eas-integration.md)

## Operator Layer

The agent IS the operator layer. No middleware, no SDK. CLI-first, `--json` everywhere.

```bash
uv run b1e55ed signal "BTC looking strong" --direction bullish --conviction 8
uv run b1e55ed alerts --since 1h --json
uv run b1e55ed producers register --name my-scanner --domain technical --endpoint http://localhost:9000/signals
uv run b1e55ed webhooks add http://my-agent/hooks --events "signal.*"
uv run b1e55ed health --json
```

### Distribution

- `skill.json` — ClawHub metadata for discoverability and installation
- `setup_operator.sh` — one-command operator setup
- `crons.json` — OpenClaw cron templates for brain cycles, health checks, and position monitoring

## Documentation

- [Getting Started](docs/getting-started.md) — setup, concepts, troubleshooting
- [CLI Reference](docs/cli-reference.md) — complete CLI surface (16 commands)
- [API Reference](docs/api-reference.md) — 24 REST endpoints under `/api/v1/`
- [Contributors](docs/contributors.md) — registry, scoring, attribution, EAS
- [Architecture](docs/architecture.md) — system design and data flow
- [Configuration](docs/configuration.md) — presets, weights, risk settings
- [Security](docs/security.md) — identity, encryption, hash chain
- [Deployment](docs/deployment.md) — production hosting
- [Learning Loop](docs/learning-loop.md) — how weights auto-adjust
- [EAS Integration](docs/eas-integration.md) — Ethereum Attestation Service
- [The Forge Spec](docs/FORGE_SPEC.md) — identity derivation ritual
- [Agent Producer Tutorial](docs/tutorial-agent-producer.md) — build a producer in 15 lines
- [OpenClaw Integration](docs/openclaw-integration.md) — operator layer design
- [Operator Sprint Plan](docs/OPERATOR_SPRINT_PLAN.md) — beta.2 build plan

## Development

```bash
# 225 tests
uv run pytest -q

# Lint and format
uv run ruff check engine/ api/ tests/
uv run ruff format engine/ api/ tests/

# Type check
uv run mypy engine/ api/
```

## License

MIT
