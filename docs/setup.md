# Setup Guide — OpenClaw + b1e55ed

Get from bare machine to a running b1e55ed instance with OpenClaw in under 30 minutes.

---

## Prerequisites

- Linux machine (Ubuntu 20.04+ recommended) or macOS
- `curl`, `git`, `python3` installed
- A Telegram account
- A GitHub account with access to `P-U-C/b1e55ed`

---

## Step 1 — Install OpenClaw

```bash
curl -fsSL https://install.openclaw.ai | bash
```

Verify:
```bash
openclaw --version
```

> **macOS**: If you get a Gatekeeper warning, run:
> ```bash
> xattr -dr com.apple.quarantine ~/.local/bin/openclaw
> ```

**Onboard and install the daemon:**

```bash
openclaw onboard --install-daemon
```

This installs OpenClaw as a background service and walks you through initial setup.

**Add your AI provider token** — use your existing subscription rather than paying per API call:

```bash
# Claude (Anthropic)
openclaw config set anthropic.api_key "YOUR_ANTHROPIC_API_KEY"

# or OpenAI
openclaw config set openai.api_key "YOUR_OPENAI_API_KEY"
```

**Check the gateway is operational:**

```bash
openclaw gateway status
```

If it is not running, check overall status and run the doctor:

```bash
openclaw status
openclaw doctor
openclaw doctor --fix
```

You should see `Doctor complete`. The gateway should now be up.

---

## Step 2 — Connect a Telegram Bot

You need a Telegram bot to receive alerts and send commands to OpenClaw.

**2a. Create the bot**

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot`
3. Follow prompts — choose a name and username (e.g. `b1e55ed_monitor_bot`)
4. Copy the token: `1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ`

**2b. Get your Telegram user ID**

1. Message [@userinfobot](https://t.me/userinfobot)
2. It replies with your ID (e.g. `505841972`)

**2c. Add your bot token to OpenClaw:**

```bash
openclaw config set telegram.bot_token "YOUR_BOT_TOKEN"
```

**2d. Pair via Telegram**

Message your bot from Telegram — it will reply with a pairing code. Then approve it on your machine:

```bash
openclaw pairing approve telegram [PAIRING_CODE]
```

**2e. Verify**

Send any message to your bot. You should get a response within a few seconds confirming it is operational.

---

## Step 3 — Install b1e55ed

```bash
curl -sSf https://raw.githubusercontent.com/P-U-C/b1e55ed/main/install.sh | bash
```

Verify:
```bash
b1e55ed --version
```

> **macOS**: Clear quarantine if needed:
> ```bash
> xattr -dr com.apple.quarantine ~/.local/bin/b1e55ed-forge
> ```

---

## Step 4 — Run the Setup Wizard

The wizard forges your node identity and registers you as a contributor:

```bash
b1e55ed wizard
```

This will:
- Generate your node keypair (~2-5 seconds with the Rust forge binary)
- Register your node with the b1e55ed oracle
- Create a GitHub issue confirming your contributor ID

Save your node ID — it appears at the end of the wizard.

---

## Step 5 — Start the Engine

```bash
b1e55ed start
```

This starts:
- **API server** on `localhost:5050`
- **Dashboard** on `localhost:5051` (opens in browser automatically)

Verify:
```bash
curl localhost:5050/health
# → {"status": "ok", ...}
```

---

## Step 6 — Install the Operator Workspace

Clone the operator template and run the installer:

```bash
git clone https://github.com/P-U-C/b1e55ed-operator-template /tmp/b1e55ed-operator-template
bash /tmp/b1e55ed-operator-template/scripts/setup-openclaw.sh
```

Then fill in two files:

**`~/.openclaw/workspace/USER.md`** — your details:
```
- Name: <your name>
- Telegram: @yourusername
- Timezone: UTC-8
- GitHub: yourusername
```

**`~/.openclaw/workspace/CRITICAL.md`** — instance state:
```
- b1e55ed version: 1.0.0-beta.8
- Node ID: <from wizard>
- API: http://localhost:5050
- Dashboard: http://localhost:5051
- GH_TOKEN: (store in env, not here)
```

---

## Step 7 — Set Up Crons

```bash
GH_TOKEN=your_github_token \
REPO=P-U-C/b1e55ed \
bash ~/.openclaw/workspace/scripts/setup-crons.sh
```

This sets up:
- `b1e55ed resolve-outcomes` every 30 minutes (outcome resolver)
- OpenClaw queue drain every 5 minutes (b1e55ing, reviews, alerts)

Verify:
```bash
crontab -l
openclaw cron list
```

---

## Step 8 — Verify Everything

```bash
bash ~/.openclaw/workspace/scripts/verify-engine.sh
```

Expected output after ~5 minutes of running:
```
✅ API: running (localhost:5050)
📡 Producer activity (last 2h):
   btc_tradfi  | 2026-03-04 02:35:00 | 3 forecasts
   sol_onchain | 2026-03-04 02:34:00 | 2 forecasts
   ...
🔄 Outcome resolver:
   Last run: 2026-03-04 02:30:00
   Total outcomes: 0 / 500 (MetaProducer activation)
   Unresolved backlog: 12
```

---

## What Happens Next

The system runs autonomously from here. The data accumulation timeline:

| Timeframe | Milestone |
|-----------|-----------|
| Hour 1 | First forecasts in DB, outcome resolver running |
| Day 3 | ~100 outcomes — first calibration data |
| Week 2 | ~300 outcomes — LLM critic and prosecutor go live (review shadow logs first) |
| Week 3-4 | **500 outcomes** — MetaProducer activates |
| Month 3 | Regime-conditional stats mature — full system live |

Monitor progress anytime:
```bash
sqlite3 ~/.b1e55ed/brain.db \
  "SELECT COUNT(*) as outcomes, ROUND(COUNT(*)*100.0/500,1) as pct FROM events WHERE type='FORECAST_OUTCOME_V1'"
```

---

## Troubleshooting

**Bot not responding in Telegram**
```bash
openclaw gateway status  # is it running?
openclaw gateway restart
```

**`b1e55ed start` crashes**
```bash
b1e55ed start --debug  # see full error
# Common: port 5050 already in use → kill existing process
lsof -ti:5050 | xargs kill -9
```

**Forge binary slow (~30 min instead of ~5 sec)**
```bash
# macOS quarantine bit still set
xattr -dr com.apple.quarantine ~/.local/bin/b1e55ed-forge
```

**Outcome resolver exits non-zero**
```bash
b1e55ed resolve-outcomes --debug
# Common: DB not initialized yet → run b1e55ed start first
```

---

*Questions? Telegram your OpenClaw instance or open an issue at [P-U-C/b1e55ed](https://github.com/P-U-C/b1e55ed/issues)*
