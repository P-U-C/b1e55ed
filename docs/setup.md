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

**Save your node ID** — it appears at the end of the wizard. You'll need it in the next step.

---

## Step 5 — Install the Operator Workspace

This sets up the OpenClaw agent workspace that gives your instance its identity and operating context.

```bash
git clone https://github.com/P-U-C/b1e55ed-operator-template /tmp/b1e55ed-operator-template
bash /tmp/b1e55ed-operator-template/scripts/setup-openclaw.sh
```

Then fill in two files with your details:

**`~/.openclaw/workspace/USER.md`** — who you are:
```
- Name: <your name>
- Telegram: @yourusername
- Timezone: UTC-8
- GitHub: yourusername
```

**`~/.openclaw/workspace/CRITICAL.md`** — your instance state (update after every significant change):
```
- b1e55ed version: 1.0.0-beta.8
- Node ID: <from wizard>
- API: http://localhost:5050
- Dashboard: http://localhost:5051
```

---

## Step 6 — Start the Engine

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

**Start the outcome resolver** (runs every 30 minutes — essential for the system to learn):

```bash
(crontab -l 2>/dev/null; echo "*/30 * * * * b1e55ed resolve-outcomes >> ~/.b1e55ed/logs/resolver.log 2>&1") | crontab -
```

This is the loop that closes: forecasts emit → horizons pass → outcomes resolve → Brier scores update → karma updates → weights shift. Without it the engine runs but never learns. The meta-producer activates after 500 resolved outcomes (~3-4 weeks).

Verify the cron is set:
```bash
crontab -l | grep resolve-outcomes
```

---

## Step 7 — Verify Everything

```bash
curl localhost:5050/health
# → {"status": "ok", ...}

b1e55ed resolve-outcomes --dry-run
# → shows pending outcomes without applying them
```

Expected state after ~5 minutes of running:

```
✅ API: running (localhost:5050)
📡 Producer activity:
   btc_tradfi  | forecasts emitting
   sol_onchain | forecasts emitting
🔄 Outcome resolver: scheduled (next run in <30 min)
   Total outcomes: 0 / 500 (MetaProducer not yet active)
```

---

## What Happens Next

The system runs autonomously from here. The data accumulation timeline:

| Timeframe | Milestone |
|-----------|-----------|
| Hour 1 | First forecasts in DB, outcome resolver running |
| Day 3 | ~100 outcomes — first calibration data visible |
| Week 2 | ~300 outcomes — LLM critic and prosecutor observing in shadow |
| Week 3–4 | **500 outcomes** — MetaProducer activates |
| Month 3 | Regime-conditional stats mature — full system live |

Check progress anytime:
```bash
sqlite3 ~/.b1e55ed/brain.db \
  "SELECT COUNT(*) as outcomes, ROUND(COUNT(*)*100.0/500,1) as pct_to_meta FROM events WHERE type='FORECAST_OUTCOME_V1'"
```

---

## Troubleshooting

**Bot not responding in Telegram**
```bash
openclaw gateway status
openclaw gateway restart
```

**`b1e55ed start` crashes**
```bash
b1e55ed start --debug
# Common: port 5050 already in use
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
# Common: DB not initialized yet — run b1e55ed start first
```

---

*Questions? Telegram your OpenClaw instance or open an issue at [P-U-C/b1e55ed](https://github.com/P-U-C/b1e55ed/issues)*
