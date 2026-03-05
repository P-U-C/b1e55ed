# Agent Operator Guide (OpenClaw)

This guide is for operators who want the **full stack**:

- b1e55ed (signals + brain + dashboard)
- OpenClaw (24/7 AI operator)
- Telegram alerts + natural-language queries
- Heartbeat health checks

If you want **no AI dependency**, start here instead:

- [Standalone Operator Guide](operator-standalone.md)

---

## What you get

Everything in the standalone deployment, plus:

- **AI monitors 24/7**: watches health, events, and anomalies
- **Telegram alerts**: sends actionable notifications (failures, thresholds, noteworthy shifts)
- **Natural-language ops**: ask questions like "what's HYPE doing?" and get a synthesized answer
- **Proactive analysis**: agent can summarize what changed since last check
- **Heartbeat checks**: a small, explicit checklist that runs periodically

---

## Architecture

```
                (your private VPS)

        +-----------------------------+
        |          b1e55ed             |
        |  - producers + brain loop    |
        |  - REST API (:5050)          |
        |  - dashboard (:5051)         |
        +--------------^--------------+
                       |
                       | localhost / tailscale
                       v
        +-----------------------------+
        |          OpenClaw           |
        |  - AI layer + heartbeats    |
        |  - alert routing + tools    |
        +--------------^--------------+
                       |
                       v
                  Telegram (Bot)

Optional: Oracle endpoint exposed so agents (or other systems) can check producer provenance.
```

---

## Prerequisites

### Same as standalone

- VPS: **2 vCPU / 2 GB RAM minimum** (4 GB recommended)
- Python 3.11+ (installer + `uv` manage this)
- GitHub access (installer pulls from GitHub)

### Additional

- **Anthropic API key** (required)
  - Create one at: https://console.anthropic.com/
  - You'll copy the key into OpenClaw during setup.
- **Telegram account** (required)
- Optional model keys (only if you plan to use them):
  - OpenAI key: https://platform.openai.com/
  - xAI key: https://console.x.ai/

⚠️ **Common failure point #1: no AI key / wrong AI key**

Symptoms: OpenClaw starts but can't run tools, or errors on model calls.

Fix: re-run `openclaw setup` and ensure the key is stored (see Step 4).

---

## Step 1: Install b1e55ed

Do the standalone install first:

```bash
# (Recommended) run as a dedicated operator user
sudo useradd -m -s /bin/bash b1e55ed
sudo su - b1e55ed

curl -sSf https://raw.githubusercontent.com/P-U-C/b1e55ed/main/install.sh | bash
export PATH="$HOME/.local/bin:$PATH"

b1e55ed wizard
```

At the end of the wizard you should be able to run `b1e55ed start`. **Do not run it manually - Step 5 installs it as a systemd service automatically.** Just confirm the wizard completes cleanly.

---

## Step 2: Install OpenClaw

Install Node.js first if you don't have it (Ubuntu):

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs
node --version
npm --version
```

Install OpenClaw:

```bash
sudo npm install -g openclaw
openclaw --version
```

Run setup (stores provider keys and creates a default workspace):

```bash
openclaw setup
```

During setup, when prompted for an Anthropic key:

- Go to https://console.anthropic.com/
- Create an API key
- Paste it into the setup prompt

---

## Step 3: Connect Telegram

### 3.1 Create a Telegram bot

1. In Telegram, open **@BotFather**
2. Send `/newbot`
3. Choose a name and username
4. BotFather will return a **bot token** (a long string)

### 3.2 Store the token in OpenClaw

On your VPS:

```bash
# Replace TOKEN with the exact token BotFather gave you.
# Example format: 1234567890:AA... (keep it secret)
openclaw config set telegram.token "TOKEN"
```

### 3.3 Test the bot

1. Open your bot in Telegram
2. Tap **Start** (or send `/start`)

If OpenClaw is running, you should see it acknowledge messages (depending on your configured skills/heartbeats).

⚠️ **Common failure point #2: Telegram bot doesn't respond**

Checklist:

```bash
# Confirm token was set
openclaw config get telegram.token

# Check OpenClaw logs (if running under systemd, see later section)
openclaw gateway status || true
```

Also confirm you are messaging the correct bot (the one you created with BotFather).

---

## Step 4: Configure the AI (SOUL.md + USER.md)

OpenClaw uses a workspace directory containing operator instructions.

Two files matter most:

- `SOUL.md`: the assistant's personality + operating principles
- `USER.md`: your preferences and what "good" looks like

**The setup script in Step 5 writes these for you** from your answers to the prompts. You do not need to create them manually.

If you want to customize after setup, edit them at `~/.openclaw/workspace/` — your own copy with your real name, Telegram handle, timezone, and node ID already filled in.

---

## Step 5: Connect b1e55ed to OpenClaw

The simplest integration pattern:

- b1e55ed runs on the VPS (API on `127.0.0.1:5050`)
- OpenClaw heartbeats call:
  - `b1e55ed health --json`
  - `curl http://127.0.0.1:5050/api/v1/health`
  - `b1e55ed status`

### 5.0 Run the operator setup scripts

Two separate scripts, two separate concerns:

**`scripts/setup-connected.sh`** — installs b1e55ed + OpenClaw + Telegram, and **registers b1e55ed as a systemd service**. Run this first if you haven't already (it's the full connected install script).

**`scripts/setup-openclaw.sh`** — configures the OpenClaw workspace (USER.md, CRITICAL.md, queue-drain cron). Run this after.

<Warning>
**Do Step 3 (Telegram bot) before running setup-openclaw.sh.** The script will ask for your bot token.
</Warning>

```bash
export GH_TOKEN="ghp_xxx"   # required for queue automation

# If starting fresh (installs everything + systemd):
bash scripts/setup-connected.sh

# OpenClaw workspace only (USER.md, CRITICAL.md, cron):
bash scripts/setup-openclaw.sh
```

`setup-openclaw.sh` prompts for: name, Telegram handle, timezone, GitHub username, bot token — then writes your workspace files with real values (no placeholders).

Verify the engine is running:

```bash
sudo systemctl status b1e55ed     # engine running?
sudo journalctl -u b1e55ed -f     # live logs
openclaw cron list                 # queue drain active?
```

### 5.1 Ensure b1e55ed is reachable locally

On the VPS (give it ~10s to start):

```bash
curl -s http://127.0.0.1:5050/api/v1/health
```

### 5.2 Create a HEARTBEAT.md

In your OpenClaw workspace, create `HEARTBEAT.md` with explicit checks.

Minimal, copy/paste-ready example:

```md
Every heartbeat:

1) b1e55ed health (cron-safe)
   - run: b1e55ed health --json
   - alert if status != OK

2) API reachable
   - run: curl -s http://127.0.0.1:5050/api/v1/health
   - alert if not HTTP 200 or body is not healthy

3) Brain freshness
   - run: b1e55ed status
   - alert if last brain cycle is stale (>10 minutes)
```

Then run a manual check to validate your environment (optional but recommended):

```bash
b1e55ed health --json
b1e55ed status
```

⚠️ **Common failure point #3: OpenClaw can't find the `b1e55ed` command**

Fix: ensure the service environment PATH includes `~/.local/bin`, or use an absolute path in your heartbeat commands.

---

## Step 6: Tailscale (recommended)

Tailscale lets you access the dashboard/API privately without exposing ports to the public internet.

### VPS install

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

After `tailscale up`, it will print a login URL. Open it, authenticate, and approve the device.

### Laptop (macOS) install

- Install from: https://tailscale.com/download
- Sign in to the same Tailscale account

Now you can bind b1e55ed to localhost and still reach it over your tailnet by using the VPS Tailscale IP and a reverse proxy or `tailscale serve` (optional). For production hardening, see [docs/deployment.md](deployment.md).

---

## Step 7: Oracle setup (end-to-end)

If you want contributor registrations and agent provenance checks to work end-to-end, ensure:

- API is running
- Oracle endpoint is reachable wherever your agent runs

Oracle docs:

- [docs/oracle.md](oracle.md)

---

## Daily operations

### What alerts look like

Typical Telegram alerts you should configure for:

- services restarting (API/brain/OpenClaw)
- `b1e55ed health` returning DEGRADED/ERROR
- brain staleness (no successful cycles within your threshold)

### Example natural-language queries

- "what's BTC doing today?"
- "summarize last 2 hours of signals"
- "is the engine healthy?"

Under the hood, OpenClaw should answer by calling:

- `b1e55ed status`
- `b1e55ed positions --json`
- API health endpoints

### How heartbeats work

Heartbeats are deliberate, small checklists. You define them in `HEARTBEAT.md`. The agent executes them on a schedule and alerts on violations.

---

## Customizing alerts

Edit `HEARTBEAT.md` to change thresholds and escalation.

Practical knobs:

- "brain stale" threshold (e.g., 10 minutes vs 30 minutes)
- which endpoints matter (API, oracle, dashboard)
- noise filtering (only alert on consecutive failures)

Keep it explicit and small so it stays reliable.

---

## Running as a service (systemd)

This section runs **four** services under systemd:

- `b1e55ed-api.service`
- `b1e55ed-brain.service`
- `openclaw-gateway.service`
- `openclaw-agent.service` (optional wrapper if you run a dedicated agent process)

### b1e55ed services

Use the unit files from the standalone guide:

- [Standalone Operator Guide → Running as a service](operator-standalone.md#running-as-a-service-systemd)

### OpenClaw gateway service

This assumes:

- OpenClaw is installed globally (`/usr/bin/openclaw` should exist)
- You want it running as the `b1e55ed` user

```bash
sudo tee /etc/systemd/system/openclaw-gateway.service >/dev/null <<'EOF'
[Unit]
Description=OpenClaw gateway
After=network.target

[Service]
Type=simple
User=b1e55ed
WorkingDirectory=/home/b1e55ed
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/home/b1e55ed/.local/bin
ExecStart=/usr/bin/openclaw gateway start
ExecStop=/usr/bin/openclaw gateway stop
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

Enable + start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now openclaw-gateway.service
systemctl status openclaw-gateway.service --no-pager
```

If your OpenClaw install path differs, locate it:

```bash
command -v openclaw
```

---

## Troubleshooting

### OpenClaw installed but `openclaw` not found

```bash
npm -g bin
command -v openclaw
sudo npm install -g openclaw
```

### Telegram connection issues

- Re-check token with `openclaw config get telegram.token`
- Ensure the bot was started in Telegram (`/start`)

### b1e55ed API not reachable from OpenClaw

```bash
curl -v http://127.0.0.1:5050/api/v1/health
systemctl status b1e55ed-api.service --no-pager || true
journalctl -u b1e55ed-api.service -n 200 --no-pager || true
```

For deeper b1e55ed ops docs, see the repo docs index in `README.md`.
