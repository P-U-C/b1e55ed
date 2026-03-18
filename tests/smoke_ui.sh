#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# b1e55ed — Smoke Test Runner
# Runs the full dashboard + API smoke test suite via TestClient
# No running servers needed — bootstraps its own temporary database
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo ""
echo "  ╔══════════════════════════════════════════════════════════╗"
echo "  ║  b1e55ed Smoke Test Suite                               ║"
echo "  ║  Dashboard Pages · HTMX Partials · API Routes           ║"
echo "  ╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Repo:     $REPO_ROOT"
echo "  Runner:   TestClient (standalone, no servers needed)"
echo "  Database: Temporary SQLite (auto-bootstrapped)"
echo ""

cd "$REPO_ROOT"

# Use venv python if available
if [ -f .venv/bin/python ]; then
    PYTHON=".venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
else
    echo "  ❌ Python not found"
    exit 1
fi

echo "  Python:   $($PYTHON --version 2>&1)"
echo ""
echo "  Running smoke tests..."
echo ""

# Run the Python smoke test suite
$PYTHON tests/smoke_api.py
EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "  ✅ All smoke tests passed"
else
    echo "  ⚠️  Some tests failed (exit code $EXIT_CODE)"
fi

exit $EXIT_CODE
