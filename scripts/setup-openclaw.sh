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
echo "  OpenClaw workspace setup complete."
echo ""
echo "  Operator:   $OPERATOR_NAME (@$OPERATOR_TG)"
echo "  Node ID:    $NODE_ID"
echo "  b1e55ed:    $B1E55ED_VERSION"
echo ""
echo "  Dashboard:  http://localhost:5051"
echo "  API:        http://localhost:5050"
echo ""
echo "  Next steps:"
echo "    1) Export GH_TOKEN if not set:"
echo "         export GH_TOKEN=ghp_xxx"
echo "    2) Start the engine:"
echo "         sudo systemctl start b1e55ed"
echo "         sudo systemctl status b1e55ed"
echo "    3) Verify queue drain cron:"
echo "         openclaw cron list"
echo "    4) Test the resolver:"
echo "         b1e55ed resolve-outcomes --dry-run"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
