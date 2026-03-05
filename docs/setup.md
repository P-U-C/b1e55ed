# Setup Guide — OpenClaw + b1e55ed

Get from bare machine to a running b1e55ed instance with OpenClaw in under 30 minutes.

---

## Prerequisites

- Linux machine (Ubuntu 20.04+ recommended) or macOS
- `curl`, `git`, `python3` installed
- A Telegram account
- A GitHub account with access to `P-U-C/b1e55ed`

---

## Step 1 — Create a Telegram Bot

You'll need a bot token before running the OpenClaw setup wizard (it asks for it).

**1a. Create the bot**

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot`
3. Follow prompts — choose a name and username (e.g. `b1e55ed_monitor_bot`)
4. Copy the token: `1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ`

**1b. Get your Telegram user ID**

1. Message [@userinfobot](https://t.me/userinfobot)
2. It replies with your ID (e.g. `505841972`)

Keep both handy — the wizard in Step 2 will ask for them.

---

## Step 2 — Install OpenClaw

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

**Onboard and install the daemon.** This wizard walks through connecting your AI provider and Telegram bot in one flow:

```bash
openclaw onboard --install-daemon
```

When prompted:
- **AI key**: use an Anthropic setup-token (Claude subscription) or OpenAI Codex token — these use your existing subscription and are the most cost-effective options
- **Bot token**: paste the token from Step 1a
- **Telegram user ID**: paste the ID from Step 1b

**Check the gateway is operational:**

```bash
openclaw gateway status
```

If it is not running:

```bash
openclaw doctor
openclaw doctor --fix
```

You should see `Doctor complete`. The gateway should now be up.

**Pair your Telegram account:**

Message your bot from Telegram — it will reply with a pairing code. Approve it:

```bash
openclaw pairing approve telegram [PAIRING_CODE]
```

Send any message to your bot to verify it responds.

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

**Save your node ID** — it appears at the end of the wizard.

---

## Step 5 — Install the Operator Workspace

This configures the OpenClaw agent workspace — your instance's identity and operating context:

```bash
git clone https://github.com/P-U-C/b1e55ed-operator-template /tmp/b1e55ed-operator-template
bash /tmp/b1e55ed-operator-template/scripts/setup-openclaw.sh
```

The script prompts for your name, Telegram handle, timezone, and GitHub username. It then:
- Detects your node ID automatically from the installed CLI
- Writes `~/.openclaw/workspace/USER.md` and `CRITICAL.md` with your real details
- Sets up the OpenClaw queue-drain cron (every 5 min)

---

## Step 6 — Start the Engine

Install b1e55ed as a persistent systemd service so it runs on boot and restarts automatically:

```bash
B1E55ED_BIN="$(command -v b1e55ed)"
CURRENT_USER="$(whoami)"
ENV_FILE="$HOME/.config/b1e55ed/b1e55ed.env"

mkdir -p "$(dirname "$ENV_FILE")"
cat > "$ENV_FILE" <<EOF
HOME=$HOME
PATH=$PATH
GH_TOKEN=${GH_TOKEN:-}
EOF
chmod 600 "$ENV_FILE"

sudo tee /etc/systemd/system/b1e55ed.service > /dev/null <<EOF
[Unit]
Description=b1e55ed profit engine
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$HOME
EnvironmentFile=$ENV_FILE
ExecStart=$B1E55ED_BIN daemon
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now b1e55ed
```

Verify:
```bash
sudo systemctl status b1e55ed
curl localhost:5050/health
# → {"status": "ok", ...}
```

View live logs:
```bash
sudo journalctl -u b1e55ed -f
```

> **Note:** Outcome resolution runs automatically every 30 minutes via `b1e55ed daemon`. No crontab needed.
>
> This is the loop that closes: forecasts emit → horizons pass → outcomes resolve → Brier scores update → karma updates → weights shift. The meta-producer activates after 500 resolved outcomes (~3-4 weeks).

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

**b1e55ed service not starting**
```bash
sudo journalctl -u b1e55ed -n 50
# Common: port 5050 already in use
lsof -ti:5050 | xargs kill -9
sudo systemctl restart b1e55ed
```

**Forge binary slow (~30 min instead of ~5 sec)**
```bash
# macOS quarantine bit still set
xattr -dr com.apple.quarantine ~/.local/bin/b1e55ed-forge
```

**Outcome resolver exits non-zero**
```bash
b1e55ed resolve-outcomes --debug
# Common: DB not initialized yet — run b1e55ed daemon first
```

---

*Questions? Telegram your OpenClaw instance or open an issue at [P-U-C/b1e55ed](https://github.com/P-U-C/b1e55ed/issues)*
