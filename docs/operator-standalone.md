---
title: "Standalone Operator Guide"
description: "Run b1e55ed without AI dependency — CLI-first, data engine only."
---

# Standalone Operator Guide (No AI)

This guide is for operators who want **the b1e55ed data + signal engine only**.

- Pure CLI (plus optional dashboard)
- No AI dependency
- Works on a single VPS

---

## What you get

- **Signal engine**: producers → events → brain synthesis
- **REST API** (`/api/v1`) for health, producers, oracle, etc.
- **Dashboard** (optional, but useful): local web UI
- **CLI control plane**: setup, brain cycles, health checks, positions, contributors
- **Systemd-ready**: single `b1e55ed daemon` process manages everything

**No AI required.** If you later want an agent layer (Telegram alerts, natural-language ops), see: [Agent Operator Guide (OpenClaw)](operator-agent.md).

---

## Prerequisites

### Minimum server

- VPS: **2 vCPU / 2 GB RAM minimum** (4 GB recommended)
- OS: Ubuntu 22.04+ (any Linux is fine; commands below assume Ubuntu)
- Disk: 20 GB

### Accounts / access

- A **GitHub account** (needed because the installer pulls from GitHub)

### Software

- Python **3.11+** (the installer will verify; `uv` manages the venv/tool)
- `curl`

Install basics (Ubuntu):

```bash
sudo apt update
sudo apt install -y curl git
```

---

## Install

Run the installer as the user that will operate the engine (recommended: a dedicated `b1e55ed` user):

```bash
# Create a non-root operator user (recommended)
sudo useradd -m -s /bin/bash b1e55ed
sudo su - b1e55ed

# Install b1e55ed (installs uv if needed; installs b1e55ed as a uv tool)
curl -sSf https://raw.githubusercontent.com/P-U-C/b1e55ed/main/install.sh | bash

# Ensure your PATH includes ~/.local/bin for this session
export PATH="$HOME/.local/bin:$PATH"

b1e55ed --version
```

⚠️ **Common failure point #1: `b1e55ed: command not found`**

Fix:

```bash
export PATH="$HOME/.local/bin:$PATH"
command -v b1e55ed
```

If that works, make it permanent:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
. ~/.bashrc
```

---

## First run (wizard)

Run:

```bash
b1e55ed wizard
```

The wizard is the recommended first command after install. It walks you through five operator-critical steps:

1. **Identity forge** (creates your contributor identity)
2. **Universe + config** (writes `config/user.yaml`)
3. **Producer registration** (enables/disables producers and schedules)
4. **First brain run** (verifies end-to-end ingestion → synthesis → storage)
5. **API setup** (so you can query health/oracle and use the dashboard)

### What the `0xb1e55ed` prefix means

You will see `0xb1e55ed` in banners and identity output.

- It's the system's **blessed hex prefix** and a human-visible marker that you're interacting with the correct toolchain.
- It also shows up in identity / provenance contexts so operators can spot "wrong box / wrong env" mistakes.

### How long does identity forge take?

The forge step is CPU-bound. Rough ballpark:

| Hardware | Typical forge time |
|---|---:|
| 2 vCPU shared VPS | 30-120 seconds |
| 4 vCPU VPS | 15-60 seconds |
| Modern laptop CPU | 5-30 seconds |

If it's taking longer, let it run. (You can also re-run identity operations later via `b1e55ed identity --help`.)

⚠️ **Common failure point #2: forge feels "stuck"**

What to do:

```bash
# Verify the process is alive
ps aux | grep -i b1e55ed | head

# If you must retry, re-run the wizard (it is designed to be re-runnable)
b1e55ed wizard
```

---

## Start the engine

### Start API + dashboard (recommended)

```bash
b1e55ed start
```

Defaults:

- API: `http://127.0.0.1:5050` (health: `/api/v1/health`)
- Dashboard: `http://127.0.0.1:5051`

To bind to a different host/ports:

```bash
b1e55ed start --host 127.0.0.1 --api-port 5050 --dashboard-port 5051 --no-browser
```

### Run the brain (signal loop only)

For a single cycle:

```bash
b1e55ed brain
```

For a fuller cycle (includes slower producers):

```bash
b1e55ed brain --full
```

---

## Core CLI commands

These are the commands you'll use daily.

| Command | What it does |
|---|---|
| `b1e55ed wizard` | First-run interactive setup (identity, config, producers, first run, API) |
| `b1e55ed start` | Starts API + dashboard together (ports 5050/5051 by default) |
| `b1e55ed brain` | Runs one brain cycle (add `--full` for slower producers) |
| `b1e55ed scan` | **Not a top-level command in current releases.** Use `b1e55ed alerts` (recent alerts) + dashboard views to "scan" system state. |
| `b1e55ed health` | Cron-safe health check (useful for monitoring) |
| `b1e55ed status` | Human-readable system status summary |
| `b1e55ed signal` | Inject operator intel (curator signal) |
| `b1e55ed positions` | Lists open positions with best-effort PnL |
| `b1e55ed contributors` | View/manage contributor reputation + provenance |

Tip: everything supports `--help`. For the full list, see [CLI reference](operations/cli-reference.mdx).

---

## Config tuning

Your operator config is at:

- `config/user.yaml`

b1e55ed loads this on startup and uses it to define:

- the **universe** (symbols)
- execution mode (**paper** vs **live**)
- producer enablement + **weights** (how much each producer influences synthesis)

### Key fields to know

(Exact keys are fully documented in [Configuration](operations/config-reference.mdx); below is the operator-focused subset.)

| Area | What to look for | Why it matters |
|---|---|---|
| Universe | `universe.symbols` | What assets get collected/scored |
| Execution | `execution.mode` (`paper`/`live`) | Controls whether execution is real |
| Producers | `producers.enabled` / `producers.weights` | Decide what data sources contribute to conviction |

### Sample config: BTC-focused

```yaml
universe:
  symbols: ["BTC"]

execution:
  mode: paper

producers:
  enabled:
    - technical-analysis
    - price-alerts
    - orderbook-depth
    - market-sentiment
    - onchain-flows
  weights:
    technical-analysis: 1.0
    price-alerts: 0.8
    orderbook-depth: 0.7
    market-sentiment: 0.5
    onchain-flows: 0.6
```

### Sample config: multi-asset (top 10)

```yaml
universe:
  symbols: ["BTC","ETH","SOL","BNB","XRP","ADA","AVAX","DOT","LINK","UNI"]

execution:
  mode: paper

producers:
  enabled:
    - technical-analysis
    - price-alerts
    - market-events
    - market-sentiment
    - social-intel
  weights:
    technical-analysis: 1.0
    price-alerts: 0.7
    market-events: 0.7
    market-sentiment: 0.6
    social-intel: 0.4
```

After editing config, restart services (or restart `b1e55ed start`).

⚠️ **Common failure point #3: YAML indentation / syntax errors**

Fix:

```bash
python -c 'import yaml,sys; yaml.safe_load(open("config/user.yaml")); print("ok")'
```

If that errors, fix the line it reports and re-run.

---

## Producer reference (13 core producers)

b1e55ed uses "producers" to collect different kinds of signals.

This table is designed for operators deciding what to enable first.

| Producer | Domain | What it does | When to enable | Cost / complexity |
|---|---|---|---|---|
| `technical-analysis` | technical | Generates TA features/signals (trend, momentum, etc.) | Baseline; usually on | Low |
| `price-alerts` | technical | Watches price moves and emits alert-like signals | If you want fast reaction / alerts | Low |
| `orderbook-depth` | technical | Pulls liquidity/imbalance metrics from an external orderbook endpoint | When you have reliable orderbook data source | Medium (needs endpoint) |
| `market-events` | events | Emits structured market events used by the system | Default-on for context | Low |
| `onchain-flows` | onchain | On-chain flow/transfer features | When operating liquid large caps / majors | Medium (API/data deps) |
| `whale-tracking` | onchain | Tracks large entity movements | When you care about large flow narratives | Medium |
| `stablecoin-supply` | onchain | Monitors stablecoin supply / issuance patterns | Macro/liquidity regime sensitivity | Medium |
| `tradfi-basis` | tradfi | TradFi basis / funding proxies | If you trade BTC/ETH and care about leverage crowding | Medium |
| `etf-flows` | tradfi | ETF flow signals (where applicable) | If you care about US market structure flows | Medium |
| `market-sentiment` | social | Sentiment signal from supported sources | If you want risk-on/off overlay | Medium |
| `social-intel` | social | Social narrative / intel ingestion | When you want discretionary "what's being talked about" | Medium |
| `curator-intel` | curator | Operator-injected signals (manual intel) | Always if humans provide inputs | Low |
| `ai-consensus` | curator | AI consensus synthesis (requires AI access) | **Standalone operators usually leave this off** | High (external AI) |

Notes:

- This guide excludes the internal `template` producer (used as a scaffold).
- Producers have schedules; the wizard helps register/enable them.

---

## Running as a service (systemd)

`b1e55ed daemon` manages all subsystems in a single process - API, dashboard, brain cycles, and outcome resolution.

**One unit, zero crontab entries.**

```bash
sudo tee /etc/systemd/system/b1e55ed.service >/dev/null <<EOF
[Unit]
Description=b1e55ed trading intelligence
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu
EnvironmentFile=-/home/ubuntu/.b1e55ed/env
ExecStart=/home/ubuntu/.local/bin/b1e55ed daemon
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now b1e55ed.service
sudo systemctl status b1e55ed.service
```

> **Note:** Replace `ubuntu` with your actual username if different.

### What the daemon runs

| Subsystem | Schedule |
|-----------|----------|
| `b1e55ed api` | Always-on (restarts on failure) |
| `b1e55ed dashboard` | Always-on (restarts on failure) |
| `b1e55ed brain` | Every 5 minutes |
| `b1e55ed brain --full` | Every 6 hours |
| `b1e55ed resolve-outcomes` | Every 30 minutes |

Brain cycles wait for the API to be healthy before starting.

### Logs

Per-process rotating logs in `~/.b1e55ed/logs/`:

```bash
tail -f ~/.b1e55ed/logs/brain.log
tail -f ~/.b1e55ed/logs/api.log
journalctl -u b1e55ed -f
```

### Tuning intervals

Override defaults in `config/user.yaml`:

```yaml
daemon:
  brain_interval_seconds: 300       # default: 5 min
  brain_full_interval_seconds: 21600 # default: 6h
  resolver_interval_seconds: 1800   # default: 30 min
```

---

## Oracle setup (optional)

The **oracle** is a read-only endpoint that exposes producer provenance for agents and other consumers.

If you are running standalone, you typically only need this if:

- you want external systems to query provenance, or
- you plan to add an agent layer later.

What to do:

1. Ensure your API is reachable (either via Tailscale or a reverse proxy)
2. Use the oracle endpoint:

```bash
curl -s http://127.0.0.1:5050/api/v1/oracle/producers/example/provenance | head
```

Full oracle docs: [docs/oracle.md](oracle.md).

---

## Troubleshooting

### API won't start / port in use

```bash
# See what is using 5050/5051
sudo ss -ltnp | grep -E ':(5050|5051)\b' || true

# If you changed ports, restart the daemon
sudo systemctl restart b1e55ed.service
```

### Brain runs but no events / everything looks empty

```bash
# Run a single cycle with stdout
b1e55ed brain --full

# Check overall status
b1e55ed status

# Check health (cron-safe)
b1e55ed health
```

### Service logs

```bash
journalctl -u b1e55ed -n 200 --no-pager
tail -f ~/.b1e55ed/logs/api.log
tail -f ~/.b1e55ed/logs/brain.log
```

### Factory reset (last resort)

If you intentionally want to remove the tool:

```bash
b1e55ed uninstall
```

For advanced deployment patterns (reverse proxy, TLS, hardening), see: [docs/deployment.md](deployment.md).
