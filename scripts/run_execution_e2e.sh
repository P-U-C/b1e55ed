#!/usr/bin/env bash
# run_execution_e2e.sh — standalone runner for execution & OMS E2E test
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV="$REPO_ROOT/.venv/bin/python"
TEST_FILE="$REPO_ROOT/tests/test_execution_e2e.py"

echo "b1e55ed Execution & OMS E2E Runner"
echo "==================================="

if [[ ! -x "$VENV" ]]; then
  echo "ERROR: venv not found at $VENV"
  exit 1
fi

if [[ ! -f "$TEST_FILE" ]]; then
  echo "ERROR: test file not found: $TEST_FILE"
  exit 1
fi

cd "$REPO_ROOT"
"$VENV" "$TEST_FILE"
EXIT_CODE=$?

if [[ $EXIT_CODE -eq 0 ]]; then
  echo ""
  echo "✅ All stages PASS"
else
  echo ""
  echo "❌ $EXIT_CODE stage(s) FAILED"
fi

exit $EXIT_CODE
