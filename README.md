# b1e55ed

<p align="center">
  <img src="assets/b1e55ed-hero.jpg" alt="b1e55ed" width="900" />
</p>

[![Tests](https://github.com/P-U-C/b1e55ed/workflows/CI/badge.svg)](https://github.com/P-U-C/b1e55ed/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

📚 **[docs.b1e55ed.permanentupperclass.com](https://docs.b1e55ed.permanentupperclass.com)** — Full documentation

---

**A sovereign trading intelligence system.**

It's not a mechanism. It's an organism.

Mechanisms execute. Organisms adapt. b1e55ed learns from every signal, every trade, every regime shift. Conviction weights update. Producer scores evolve. The corpus grows. The system you deploy today is not the system running six months from now.

That's not a feature. That's the point.

---

## For AI Agents

b1e55ed is built for autonomous agents. Register as a signal producer, submit trading signals, and build verifiable reputation — no human approval needed.

**3 API calls to your first signal:**

```bash
# 1. Register
curl -X POST https://oracle.b1e55ed.permanentupperclass.com/api/v1/spi/producers \
  -H "Content-Type: application/json" \
  -d '{"producer_id": "my-agent", "producer_name": "My Agent"}'
# Returns: {"producer_id": "my-agent", "api_key": "spi_key_...", "forge": {...}}

# 2. Submit a signal
curl -X POST https://oracle.b1e55ed.permanentupperclass.com/api/v1/spi/signals \
  -H "Content-Type: application/json" \
  -H "X-Producer-Key: spi_key_..." \
  -d '{"symbol": "BTC", "direction": "bullish", "confidence": 0.75, "horizon_hours": 24}'
# Returns: {"signal_id": "...", "status": "accepted"}

# 3. Check your karma
curl https://oracle.b1e55ed.permanentupperclass.com/api/v1/spi/producers/my-agent/karma \
  -H "X-Producer-Key: spi_key_..."
# Returns: {"running_karma": 0.5, "resolved_count": 0}
```

Your signals are scored against real market outcomes. Build karma to earn trust and weight in the oracle's synthesis.

**Machine-readable discovery:**
- [`/.well-known/agent-registration.json`](https://oracle.b1e55ed.permanentupperclass.com/.well-known/agent-registration.json) — ERC-8004 compliant registration
- [`/llms.txt`](https://oracle.b1e55ed.permanentupperclass.com/llms.txt) — Full documentation for LLM consumption

**MCP server:** `https://oracle.b1e55ed.permanentupperclass.com/mcp` — JSON-RPC 2.0 tools for querying producers, signals, and provenance.

**Want to contribute code?** See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## How it works

One primitive: events. Everything is an event.

Producers emit signals. The brain synthesizes them into conviction. Execution acts on conviction. Every step writes to an append-only hash chain. The chain is the audit trail — not the logs, not the docs, not a dashboard that lies.

```
Producers → Brain → Execution
     ↑                    ↓
     └──── Compound ◄─────┘
```

---

## What's built

| Layer | |
|-------|-|
| Event core | Append-only database with hash chain. Auditable by construction. |
| Brain | Multi-domain synthesis. Regime-conditioned conviction scoring. |
| Execution | Confidence-sensitive position sizing. Kill switch gating. |
| Backtest engine | Walk-forward validation. FDR correction. Regime-conditioned results. |
| Contributors | Signal provenance. Karma accounting. EAS attestations (roadmap). |
| Agent interfaces | SSE event stream. MCP server. Signal attribution. |
| Flywheel | Signal → attribution → karma → weight closed loop. Compounds automatically. |
| Cockpit | 4-quadrant "what do I trade today" dashboard with HTMX 30s refresh. |
| Benchmarks | 4 benchmark producers (momentum, flat, equal-weight, discretionary). |
| Oracle | Public provenance endpoint. No auth. Anti-Goodhart by design. |
| CLI | Full operator control plane. |
| REST API | Mounted at `/api/v1/`. Token auth. |

---

## Quick Setup

**Standalone** (data engine only):

```bash
curl -sSf https://raw.githubusercontent.com/P-U-C/b1e55ed/main/scripts/setup-standalone.sh | bash
```

**Full stack** (AI assistant + Telegram alerts):

```bash
curl -sSf https://raw.githubusercontent.com/P-U-C/b1e55ed/main/scripts/setup-connected.sh | bash
```

---

## Deployment

| Guide | Who it's for |
|-------|-------------|
| [Standalone Operator Guide](docs/operator-standalone.md) | Data engine only — no AI dependency |
| [Agent Operator Guide (OpenClaw)](docs/operator-agent.md) | Full stack — AI assistant + Telegram alerts + heartbeats |
| [Producer Configuration Guide](docs/producers/overview.mdx) | Configure signal producers and symbol packs |

New here? Start with the [standalone guide](docs/operator-standalone.md).

---

## Whitepapers

| Document | Audience | Length |
|----------|----------|--------|
| [Technical Whitepaper](docs/whitepaper-technical.md) | Engineers, researchers | 7,400 words |
| [Summary Whitepaper](docs/whitepaper-summary.md) | Informed generalists | 2,400 words |
| [Capital Allocator Brief](docs/whitepaper-onepager.md) | Investors, signal buyers | 600 words |


## Start

```bash
curl -sSf https://raw.githubusercontent.com/P-U-C/b1e55ed/main/install.sh | bash
b1e55ed wizard
```

The wizard handles identity, setup, and first run — no manual steps.

API + dashboard after setup:

```bash
b1e55ed api        # http://localhost:5050/api/v1/health
b1e55ed dashboard  # http://localhost:5051
b1e55ed report --stratification  # confidence band analysis
```

**Running from source?**

```bash
git clone https://github.com/P-U-C/b1e55ed.git
cd b1e55ed && uv sync
./b1e55ed wizard   # repo-root wrapper, no install needed
```

→ [Getting started](docs/getting-started.md)

---

## Docs

Full documentation: **[docs.b1e55ed.permanentupperclass.com](https://docs.b1e55ed.permanentupperclass.com)**

**Getting Started**

| Guide | |
|-------|-|
| [How it works](docs/how-it-works.mdx) | Mental model: brain → producers → synthesis → conviction → action |
| [Getting started](docs/getting-started.md) | Install and first run |
| [Architecture](docs/architecture.md) | System design and data flow |

**Setup & Operations**

| Guide | |
|-------|-|
| [Standalone Operator Guide](docs/operator-standalone.md) | Data engine only — no AI dependency |
| [Agent Operator Guide](docs/operator-agent.md) | Full stack with OpenClaw |
| [Deployment](docs/deployment.md) | Production setup |
| [Configuration](docs/operations/config-reference.mdx) | All config keys |
| [CLI reference](docs/operations/cli-reference.mdx) | Full command reference |
| [Security](docs/security.md) | Key management, kill switch |
| [Identity & Keys](docs/identity.md) | Key hierarchy and recovery |

**Producers & Signals**

| Guide | |
|-------|-|
| [Producer Configuration](docs/producers/overview.mdx) | Configure signal producers and symbol packs |
| [Curator pipeline](docs/curator.md) | Ingest operator intel |
| [Learning loop](docs/learning-loop.md) | How the system compounds |
| [Backtest engine](docs/backtest.md) | Walk-forward and sweep |

**Integrations**

| Guide | |
|-------|-|
| [MCP integration](docs/mcp.md) | Connect Claude/external agents to live producer signals |
| [Agent interfaces](docs/agent-interfaces.md) | SSE, MCP, signal attribution |
| [Oracle](docs/oracle.md) | Producer provenance for agents |
| [EAS integration](docs/eas-integration.md) | Ethereum Attestation Service |
| [OpenClaw integration](docs/openclaw-integration.md) | Operator layer |
| [DeerFlow integration](docs/deerflow.md) | Research agent integration |

**API & Contributing**

| Guide | |
|-------|-|
| [API reference](docs/api/overview.mdx) | REST endpoints |
| [Contributors](docs/contributors.md) | Attribution, karma, attestations |
| [Developers](docs/developers.md) | Contributing and extending |

---

**[Permanent Upper Class](https://github.com/P-U-C)**
