#!/usr/bin/env bash
set -euo pipefail

# b1e55ed setup script
# - Detect Python 3.11+
# - Detect/install uv
# - uv sync
# - Optional: OpenClaw, Tailscale checks
# - Create ~/.b1e55ed/
# - Generate identity key silently (DECISIONS_V3 #11)
# - Run interactive `b1e55ed setup`

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say() { printf "%s\n" "$*"; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

python_ok() {
  python3 - <<'PY'
import sys
major, minor = sys.version_info[:2]
print(f"{major}.{minor}")
sys.exit(0 if (major, minor) >= (3, 11) else 1)
PY
}

install_uv() {
  if need_cmd uv; then
    return 0
  fi
  if need_cmd curl; then
    say "uv not found. Installing via https://astral.sh/uv/install.sh"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # shellcheck disable=SC1090
    [ -f "$HOME/.cargo/env" ] && source "$HOME/.cargo/env" || true
  else
    say "uv not found and curl is unavailable. Install uv manually: https://docs.astral.sh/uv/"
    return 1
  fi

  need_cmd uv
}

main() {
  say "b1e55ed setup"
  say "repo: ${REPO_ROOT}"

  if ! need_cmd python3; then
    say "error: python3 not found"
    exit 1
  fi

  if ! python_ok >/dev/null; then
    say "error: Python 3.11+ required. Found: $(python_ok || true)"
    exit 1
  fi

  install_uv

  (cd "${REPO_ROOT}" && uv sync --dev)

  if need_cmd openclaw; then
    say "OpenClaw detected (optional integration available)."
  else
    say "OpenClaw not detected (optional)."
  fi

  if need_cmd tailscale; then
    say "Tailscale detected (recommended for remote ops)."
  else
    say "Tailscale not detected (recommended)."
  fi

  mkdir -p "$HOME/.b1e55ed"

  # Generate identity silently.
  (cd "${REPO_ROOT}" && uv run python -c "from engine.security.identity import ensure_identity; ensure_identity()" >/dev/null)

  say "Launching interactive onboarding."
  say "You can re-run anytime: b1e55ed setup"

  (cd "${REPO_ROOT}" && uv run b1e55ed setup)

  say ""
  say "Setup complete. Next steps:"
  say "- Run one cycle:  uv run b1e55ed brain"
  say "- API server:     uv run b1e55ed api"
  say "- Dashboard:      uv run b1e55ed dashboard"
}

main "$@"
