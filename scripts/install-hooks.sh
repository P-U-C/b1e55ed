#!/usr/bin/env bash
# Install local git hooks from scripts/.
# Run once after cloning: bash scripts/install-hooks.sh
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
HOOKS_DIR="$REPO_ROOT/.git/hooks"

install_hook() {
  local name="$1"
  local src="$REPO_ROOT/scripts/$name.sh"

  if [[ ! -f "$src" ]]; then
    echo "⚠️  No script found for hook: $name (expected $src)"
    return
  fi

  ln -sf "$src" "$HOOKS_DIR/$name"
  chmod +x "$HOOKS_DIR/$name"
  echo "✅ Installed: .git/hooks/$name → scripts/$name.sh"
}

install_hook pre-commit

echo ""
echo "Hooks installed. Run 'git commit' as normal — hooks fire automatically."
echo "To skip once: git commit --no-verify"
