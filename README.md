# b1e55ed

<p align="center">
  <img src="assets/b1e55ed-hero.jpg" alt="b1e55ed" width="900" />
</p>

[![Tests](https://github.com/P-U-C/b1e55ed/workflows/CI/badge.svg)](https://github.com/P-U-C/b1e55ed/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

**A sovereign trading intelligence system.**

It's not a mechanism. It's an organism.

Mechanisms execute. Organisms adapt. b1e55ed learns from every signal, every trade, every regime shift. Conviction weights update. Producer scores evolve. The corpus grows. The system you deploy today is not the system running six months from now.

That's not a feature. That's the point.

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
| Execution | Dynamic Kelly sizing. Kill switch gating. |
| Backtest engine | Walk-forward validation. FDR correction. Regime-conditioned results. |
| Contributors | Signal provenance. Karma accounting. EAS attestations. |
| Agent interfaces | SSE event stream. MCP server. Signal attribution. |
| Oracle | Public provenance endpoint. No auth. Anti-Goodhart by design. |
| CLI | Full operator control plane. |
| REST API | Mounted at `/api/v1/`. Token auth. |

---

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

| Guide | |
|-------|-|
| [Getting started](docs/getting-started.md) | Install and first run |
| [Architecture](docs/architecture.md) | System design and data flow |
| [Configuration](docs/configuration.md) | All config keys |
| [CLI reference](docs/cli-reference.md) | Full command reference |
| [API reference](docs/api-reference.md) | REST endpoints |
| [Agent interfaces](docs/agent-interfaces.md) | SSE, MCP, signal attribution |
| [Oracle](docs/oracle.md) | Producer provenance for agents |
| [Curator pipeline](docs/curator.md) | Ingest operator intel |
| [Contributors](docs/contributors.md) | Attribution, karma, attestations |
| [Learning loop](docs/learning-loop.md) | How the system compounds |
| [Backtest engine](docs/backtest.md) | Walk-forward and sweep |
| [Security](docs/security.md) | Key management, kill switch |
| [Deployment](docs/deployment.md) | Production setup |
| [Developers](docs/developers.md) | Contributing and extending |
| [OpenClaw integration](docs/openclaw-integration.md) | Operator layer |

---

**[Permanent Upper Class](https://github.com/P-U-C)**
