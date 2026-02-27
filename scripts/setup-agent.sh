#!/usr/bin/env bash
set -euo pipefail

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
die()  { echo -e "${RED}✗${NC} $*"; exit 1; }

have() { command -v "$1" &>/dev/null; }

set_env_line() {
  # set_env_line KEY VALUE FILE
  local k="$1" v="$2" f="$3"
  mkdir -p "$(dirname "$f")"
  touch "$f"
  if grep -q "^${k}=" "$f"; then
    # Replace (Linux sed)
    sed -i "s|^${k}=.*|${k}=${v}|" "$f" || {
      # Fallback: append if sed fails
      echo "${k}=${v}" >> "$f"
    }
  else
    echo "${k}=${v}" >> "$f"
  fi
}

echo "╔══════════════════════════════════════════╗"
echo "║   b1e55ed — agent setup (OpenClaw + TG)   ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# [1/5] Check / install uv
if ! have uv; then
  echo "[1/5] Installing uv..."
  have curl || die "curl is required to install uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
ok "uv $(uv --version)"

# [2/5] Install b1e55ed
echo ""
echo "[2/5] Installing b1e55ed..."
BRANCH="${BRANCH:-main}"
have curl || die "curl is required to install b1e55ed"
curl -sSf "https://raw.githubusercontent.com/P-U-C/b1e55ed/${BRANCH}/install.sh" | bash
export PATH="$HOME/.local/bin:$PATH"
ok "b1e55ed $(b1e55ed --version 2>/dev/null || echo 'installed')"

# [3/5] Install OpenClaw
echo ""
echo "[3/5] Installing OpenClaw..."
if ! have node || ! have npm; then
  warn "node/npm not found — installing via nvm (LTS)"
  have curl || die "curl is required to install nvm"
  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
  # shellcheck disable=SC1090
  export NVM_DIR="$HOME/.nvm"
  # shellcheck disable=SC1090
  [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
  command -v nvm &>/dev/null || die "nvm install failed"
  nvm install --lts
fi
npm install -g openclaw
ok "openclaw $(openclaw --version 2>/dev/null || echo 'installed')"

# [4/5] API keys
echo ""
echo "[4/5] API keys"
echo "      Anthropic key is required for OpenClaw agents."
read -r -p "      ANTHROPIC_API_KEY: " ANTHROPIC_API_KEY
if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  die "ANTHROPIC_API_KEY is required"
fi
ENV_FILE="$HOME/.openclaw/.env"
set_env_line "ANTHROPIC_API_KEY" "$ANTHROPIC_API_KEY" "$ENV_FILE"
ok "Wrote Anthropic key to $ENV_FILE"

# [5/5] Telegram bot setup
echo ""
echo "[5/5] Telegram bot setup"
echo "      1. Open Telegram and message @BotFather"
echo "      2. Send /newbot and follow the prompts"
echo "      3. Copy the token it gives you"
echo ""
read -r -p "      Bot token (or press Enter to skip): " TG_TOKEN
if [[ -n "${TG_TOKEN:-}" ]]; then
  openclaw config set telegram.botToken "$TG_TOKEN" 2>/dev/null || \
    echo "TELEGRAM_BOT_TOKEN=$TG_TOKEN" >> "$ENV_FILE"
  ok "Telegram configured"
else
  warn "Skipping Telegram (run: openclaw config set telegram.botToken YOUR_TOKEN)"
fi

echo ""
echo "Next:"
echo "  - Run: b1e55ed wizard"
echo "  - Then: b1e55ed start"
