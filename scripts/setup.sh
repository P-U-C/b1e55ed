#!/usr/bin/env bash
set -euo pipefail

# Setup is intentionally conservative.
# No secrets are written. Use env vars.

echo "b1e55ed setup"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found. Install: pip install uv"
  exit 1
fi

uv sync --dev

echo "Done. Next: uv run pytest tests/ -v"
