#!/usr/bin/env bash
set -euo pipefail

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
die()  { echo -e "${RED}✗${NC} $*"; exit 1; }

have() { command -v "$1" &>/dev/null; }

echo "╔══════════════════════════════════════════╗"
echo "║          b1e55ed — standalone setup       ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# [1/4] Check / install uv
if ! have uv; then
  echo "[1/4] Installing uv..."
  have curl || die "curl is required to install uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
ok "uv $(uv --version)"

# [2/4] Install b1e55ed
echo ""
echo "[2/4] Installing b1e55ed..."
BRANCH="${BRANCH:-main}"
have curl || die "curl is required to install b1e55ed"
curl -sSf "https://raw.githubusercontent.com/P-U-C/b1e55ed/${BRANCH}/install.sh" | bash
export PATH="$HOME/.local/bin:$PATH"
ok "b1e55ed $(b1e55ed --version 2>/dev/null || echo 'installed')"

# [3/4] Run wizard
echo ""
echo "[3/4] Running setup wizard..."
echo "      This will create your identity and configure your node."
echo "      Note: identity forge may take a few minutes on slow hardware."
echo ""
b1e55ed wizard

# [4/4] Service setup (Linux only)
echo ""
echo "[4/4] Run as a background service? (recommended)"
read -r -p "      Install systemd service? [y/N] " response

if [[ "$response" =~ ^[Yy]$ ]]; then
  if [[ "$(uname -s)" != "Linux" ]]; then
    warn "Not Linux — skipping systemd service install"
  elif ! have systemctl; then
    warn "systemctl not found — skipping systemd service install"
  elif ! have sudo; then
    warn "sudo not found — skipping systemd service install"
  else
    echo "      Writing /etc/systemd/system/b1e55ed.service ..."
    sudo tee /etc/systemd/system/b1e55ed.service >/dev/null <<'UNIT'
[Unit]
Description=b1e55ed trading intelligence
After=network.target

[Service]
Type=simple
User=%i
WorkingDirectory=/home/%i
ExecStart=/home/%i/.local/bin/b1e55ed start
Restart=on-failure
RestartSec=10
Environment=PATH=/home/%i/.local/bin:/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=multi-user.target
UNIT

    sudo systemctl daemon-reload || warn "systemctl daemon-reload failed"
    if sudo systemctl enable --now b1e55ed.service; then
      ok "Services installed and started"
    else
      warn "Could not start service automatically (try: sudo systemctl start b1e55ed.service)"
    fi
  fi
else
  echo ""
  echo "Start manually with:"
  echo "  b1e55ed start"
fi

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║           Setup complete! ✓              ║"
echo "║                                          ║"
echo "║  Dashboard: http://localhost:5051        ║"
echo "║  API:       http://localhost:5050        ║"
echo "║                                          ║"
echo "║  Next: b1e55ed brain                     ║"
echo "╚══════════════════════════════════════════╝"
