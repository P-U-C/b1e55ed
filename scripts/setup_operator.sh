#!/usr/bin/env bash
set -euo pipefail

# b1e55ed operator setup helper.
# Goal: get from repo clone to a working local operator loop.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_PATH="${REPO_ROOT}/config/user.yaml"
IDENTITY_PATH="${HOME}/.b1e55ed/identity.key"

say() { printf "%s\n" "$*"; }

have_cmd() { command -v "$1" >/dev/null 2>&1; }

run_b1e55ed() {
  # Prefer a global install. Fall back to `uv run` when running from source.
  if have_cmd b1e55ed; then
    b1e55ed "$@"
    return
  fi

  if have_cmd uv; then
    (cd "${REPO_ROOT}" && uv run b1e55ed "$@")
    return
  fi

  say "error: b1e55ed is not installed and uv is not available"
  say "- install uv: https://astral.sh/uv"
  say "- or install b1e55ed into your environment"
  exit 2
}

is_configured() {
  [[ -f "${CONFIG_PATH}" ]] && [[ -f "${IDENTITY_PATH}" ]]
}

say "b1e55ed operator setup"
say "- repo: ${REPO_ROOT}"

if have_cmd b1e55ed; then
  say "- b1e55ed: $(command -v b1e55ed)"
else
  say "- b1e55ed: not on PATH (will try uv run)"
fi

if [[ -z "${B1E55ED_MASTER_PASSWORD:-}" ]]; then
  say ""
  say "B1E55ED_MASTER_PASSWORD is not set."
  say "This password encrypts identity material at rest."
  say ""
  read -r -p "Set it for this shell session now (recommended) [y/N]: " setpw
  if [[ "${setpw}" == "y" || "${setpw}" == "Y" ]]; then
    read -r -s -p "Enter B1E55ED_MASTER_PASSWORD: " pw
    echo
    export B1E55ED_MASTER_PASSWORD="${pw}"
    unset pw
  fi
fi

if is_configured; then
  say ""
  say "Detected existing configuration:"
  say "- config:   ${CONFIG_PATH}"
  say "- identity: ${IDENTITY_PATH}"
else
  say ""
  say "No complete configuration detected."
  say "Running setup."
  say ""
  run_b1e55ed setup
fi

say ""
say "Testing configured keys (best-effort)."
# `keys` may not exist in older builds. Do not fail setup on this.
if run_b1e55ed keys test >/dev/null 2>&1; then
  run_b1e55ed keys test
else
  say "- keys test: not available in this build"
  say "- next step: run 'b1e55ed --help' to see available commands"
fi

say ""
read -r -p "Start dashboard now [y/N]: " startdash
if [[ "${startdash}" == "y" || "${startdash}" == "Y" ]]; then
  say ""
  say "Starting dashboard (foreground)."
  say "Open http://localhost:5051"
  say ""
  run_b1e55ed dashboard
  exit 0
fi

say ""
say "Next steps"
say "- Run a brain cycle: b1e55ed brain"
say "- Check status:       b1e55ed status"
say "- Start API:          b1e55ed api"
say "- Start dashboard:    b1e55ed dashboard"
