#!/usr/bin/env bash
set -euo pipefail

TEMPLATE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE="${WORKSPACE:-$HOME/.openclaw/workspace}"
REPO="${REPO:-P-U-C/b1e55ed}"

echo "[setup] template root: $TEMPLATE_ROOT"
echo "[setup] workspace:     $WORKSPACE"
echo "[setup] repo:          $REPO"

mkdir -p "$WORKSPACE" "$WORKSPACE/scripts" "$WORKSPACE/memory" "$WORKSPACE/data"

# ─── helpers ─────────────────────────────────────────────────────────────────

copy_if_missing() {
  local src="$1" dst="$2"
  if [[ -e "$dst" ]]; then
    echo "[setup] skip existing: $dst"
  else
    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst"
    echo "[setup] copied: $dst"
  fi
}

prompt() {
  # prompt <varname> <prompt_text> [default]
  local varname="$1" prompt_text="$2" default="${3:-}"
  local value=""
  if [[ -n "$default" ]]; then
    read -rp "  $prompt_text [$default]: " value
    value="${value:-$default}"
  else
    while [[ -z "$value" ]]; do
      read -rp "  $prompt_text: " value
    done
  fi
  printf -v "$varname" '%s' "$value"
}

# ─── interactive onboarding prompts ──────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  b1e55ed operator onboarding"
echo "  Answer a few questions to configure your workspace."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

prompt OPERATOR_NAME     "Your name (e.g. Alice)"
prompt OPERATOR_TG       "Your Telegram username (without @, e.g. alice)"
prompt OPERATOR_TZ       "Your timezone (e.g. UTC-8, America/Vancouver)" "UTC"
prompt OPERATOR_GH       "Your GitHub username"
prompt TELEGRAM_BOT_TOKEN "Telegram bot token (from BotFather — do Step 2 first)"

echo ""

# ─── detect node ID ──────────────────────────────────────────────────────────

NODE_ID=""
B1E55ED_BIN="$(command -v b1e55ed 2>/dev/null || true)"

if [[ -n "$B1E55ED_BIN" ]]; then
  echo "[setup] detecting node ID..."
  NODE_ID="$("$B1E55ED_BIN" node-id 2>/dev/null || true)"
fi

if [[ -z "$NODE_ID" ]]; then
  # Fallback: read from known state files
  for f in \
    "$HOME/.b1e55ed/node_id" \
    "$HOME/.local/share/b1e55ed/node_id" \
    "$HOME/.config/b1e55ed/node_id"; do
    if [[ -f "$f" ]]; then
      NODE_ID="$(cat "$f")"
      break
    fi
  done
fi

if [[ -z "$NODE_ID" ]]; then
  echo "[setup] WARNING: could not detect node ID — fill in manually after wizard completes"
  NODE_ID="<run: b1e55ed wizard to generate>"
else
  echo "[setup] node ID: $NODE_ID"
fi

# ─── detect b1e55ed version ──────────────────────────────────────────────────

B1E55ED_VERSION="unknown"
if [[ -n "$B1E55ED_BIN" ]]; then
  B1E55ED_VERSION="$("$B1E55ED_BIN" --version 2>/dev/null | awk '{print $NF}' || echo "unknown")"
fi

# ─── copy core workspace files (non-interactive templates) ───────────────────

for f in SOUL.md AGENTS.md HEARTBEAT.md TOOLS.md BOOTSTRAP.md TASK_QUEUE.md; do
  copy_if_missing "$TEMPLATE_ROOT/$f" "$WORKSPACE/$f"
done

copy_if_missing "$TEMPLATE_ROOT/scripts/enqueue-pending-reviews.sh" "$WORKSPACE/scripts/enqueue-pending-reviews.sh"
chmod +x "$WORKSPACE/scripts/enqueue-pending-reviews.sh"

# ─── write USER.md with real values ──────────────────────────────────────────

USER_MD="$WORKSPACE/USER.md"
if [[ -e "$USER_MD" ]]; then
  echo "[setup] skip existing: $USER_MD"
else
  cat > "$USER_MD" <<EOF
# USER.md - About Your Operator

- **Name:** $OPERATOR_NAME
- **Telegram:** @$OPERATOR_TG
- **Timezone:** $OPERATOR_TZ
- **GitHub:** $OPERATOR_GH
- **b1e55ed instance:** http://localhost:5050
- **Notification preferences:** urgent only
EOF
  echo "[setup] created: $USER_MD"
fi

# ─── write CRITICAL.md with real values ──────────────────────────────────────

CRITICAL_MD="$WORKSPACE/CRITICAL.md"
if [[ -e "$CRITICAL_MD" ]]; then
  echo "[setup] skip existing: $CRITICAL_MD"
else
  cat > "$CRITICAL_MD" <<EOF
# CRITICAL.md — Operational State

## Engine Status
- **b1e55ed version**: $B1E55ED_VERSION
- **Node ID**: $NODE_ID
- **API**: http://localhost:5050
- **Dashboard**: http://localhost:5051
- **Started**: $(date -u +"%Y-%m-%dT%H:%M:%SZ")

## Producers Active
- (populated on first start)

## Outcome Resolver
- **Last run**: never
- **Total resolved**: 0
- **Target (activation)**: 500

## Alerts
- (none)
EOF
  echo "[setup] created: $CRITICAL_MD"
fi

# ─── seed queue and heartbeat state ──────────────────────────────────────────

if [[ ! -f "$WORKSPACE/task-queue.json" ]]; then
  cat > "$WORKSPACE/task-queue.json" <<'JSON'
{
  "tasks": [],
  "last_drained": null
}
JSON
  echo "[setup] created: $WORKSPACE/task-queue.json"
fi

if [[ ! -f "$WORKSPACE/memory/heartbeat-state.json" ]]; then
  cat > "$WORKSPACE/memory/heartbeat-state.json" <<'JSON'
{
  "lastChecks": {
    "producer_health": 0,
    "outcome_resolver": 0,
    "resolution_backlog": 0,
    "metaproducer_progress": 0,
    "db_health": 0,
    "pending_reviews": 0,
    "unblessed_prs": 0
  },
  "last_blessed_pr": 0
}
JSON
  echo "[setup] created: $WORKSPACE/memory/heartbeat-state.json"
fi

# ─── write Telegram token to OpenClaw config ─────────────────────────────────

OPENCLAW_ENV="$HOME/.openclaw/.env"
if grep -q "TELEGRAM_BOT_TOKEN" "$OPENCLAW_ENV" 2>/dev/null; then
  echo "[setup] TELEGRAM_BOT_TOKEN already in $OPENCLAW_ENV"
else
  echo "TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN" >> "$OPENCLAW_ENV"
  echo "[setup] wrote TELEGRAM_BOT_TOKEN to $OPENCLAW_ENV"
fi

# ─── install b1e55ed as systemd service ──────────────────────────────────────

SERVICE_NAME="b1e55ed"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
CURRENT_USER="$(whoami)"
B1E55ED_BIN_PATH="$(command -v b1e55ed 2>/dev/null || echo "$HOME/.local/bin/b1e55ed")"

echo "[setup] installing b1e55ed systemd service..."

# Build env file for systemd (inherits GH_TOKEN etc from current shell env)
SYSTEMD_ENV_FILE="$HOME/.config/b1e55ed/b1e55ed.env"
mkdir -p "$(dirname "$SYSTEMD_ENV_FILE")"
cat > "$SYSTEMD_ENV_FILE" <<EOF
# b1e55ed service environment — generated by setup-openclaw.sh
HOME=$HOME
PATH=$PATH
GH_TOKEN=${GH_TOKEN:-}
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
EOF
chmod 600 "$SYSTEMD_ENV_FILE"

SYSTEMD_UNIT="[Unit]
Description=b1e55ed profit engine
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$HOME
EnvironmentFile=$SYSTEMD_ENV_FILE
ExecStart=$B1E55ED_BIN_PATH start --no-browser
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"

if sudo tee "$SERVICE_FILE" > /dev/null <<< "$SYSTEMD_UNIT" 2>/dev/null; then
  sudo systemctl daemon-reload
  sudo systemctl enable "$SERVICE_NAME"
  sudo systemctl start "$SERVICE_NAME"
  echo "[setup] b1e55ed systemd service installed, enabled, and started"
  echo "[setup] check status: sudo systemctl status b1e55ed"
  echo "[setup] view logs:    sudo journalctl -u b1e55ed -f"
else
  echo "[setup] WARNING: sudo required to install systemd service."
  echo "        Run manually as root:"
  echo ""
  echo "  sudo tee $SERVICE_FILE > /dev/null <<'UNIT'"
  echo "$SYSTEMD_UNIT"
  echo "UNIT"
  echo "  sudo systemctl daemon-reload && sudo systemctl enable --now b1e55ed"
  echo ""
  echo "  Or for non-root, use a user-level service:"
  echo "  mkdir -p ~/.config/systemd/user"
  echo "  # copy unit above to ~/.config/systemd/user/b1e55ed.service"
  echo "  systemctl --user enable --now b1e55ed"
fi

# ─── OpenClaw queue-drain cron ───────────────────────────────────────────────

if command -v openclaw >/dev/null 2>&1; then
  existing_id="$({ openclaw cron list --json 2>/dev/null || true; } | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    data = {'jobs': []}
for job in data.get('jobs', []):
    if job.get('name') == 'b1e55ed Queue Drain (5min)':
        print(job.get('id', ''))
        break
" 2>/dev/null || true)"

  if [[ -n "$existing_id" ]]; then
    echo "[setup] queue drain cron already exists: $existing_id"
  else
    DRAIN_MSG="Read $WORKSPACE/task-queue.json and follow $WORKSPACE/TASK_QUEUE.md.

STEP 0: Run: REPO=$REPO GH_TOKEN=\${GH_TOKEN} QUEUE_PATH=$WORKSPACE/task-queue.json bash $WORKSPACE/scripts/enqueue-pending-reviews.sh

STEP 1: For each pending task (priority desc, created_at asc): set processing, increment attempts, execute by type.
- b1e55ing: spawn a Codex subagent (do NOT execute inline)
- review: run review council flow
- address_review: address concern/block findings, test, commit, push, comment
- notify: send notification
- custom: execute instruction

STEP 2: On success mark done. On failure set failed; retry next cycle if attempts < max_attempts. Write queue updates back. Update last_drained."

    openclaw cron add \
      --name "b1e55ed Queue Drain (5min)" \
      --description "Drains b1e55ed operator task queue" \
      --every 5m \
      --session isolated \
      --no-deliver \
      --message "$DRAIN_MSG" \
      2>/dev/null && echo "[setup] created queue drain cron" \
      || echo "[setup] WARNING: failed to add queue drain cron (run openclaw cron add manually)"
  fi
else
  echo "[setup] WARNING: openclaw CLI not found; skipping cron setup"
fi

# ─── done ────────────────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Setup complete."
echo ""
echo "  Operator:   $OPERATOR_NAME (@$OPERATOR_TG)"
echo "  Node ID:    $NODE_ID"
echo "  b1e55ed:    $B1E55ED_VERSION"
echo ""
echo "  Service:    sudo systemctl status b1e55ed"
echo "  Logs:       sudo journalctl -u b1e55ed -f"
echo "  Dashboard:  http://localhost:5051"
echo "  API:        http://localhost:5050"
echo ""
echo "  Next: run 'b1e55ed wizard' if you haven't forged your identity yet."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
