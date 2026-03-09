#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────
# smoke_test_producers.sh — Standalone producer smoke test runner
#
# Runs every registered producer with a temp DB, reports PASS/SKIP/FAIL
# per producer, and outputs a summary table.
#
# Usage:
#   ./scripts/smoke_test_producers.sh           # run all
#   ./scripts/smoke_test_producers.sh --json    # also print JSON path
#   ./scripts/smoke_test_producers.sh --pytest  # run via pytest (verbose)
# ──────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
TEST_FILE="$PROJECT_ROOT/tests/e2e/test_producer_smoke.py"

cd "$PROJECT_ROOT"

# ── Preflight ────────────────────────────────────────────────────────────

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "❌ Python venv not found at $VENV_PYTHON"
    echo "   Run: uv sync"
    exit 1
fi

if [[ ! -f "$TEST_FILE" ]]; then
    echo "❌ Test file not found: $TEST_FILE"
    exit 1
fi

# ── Parse args ───────────────────────────────────────────────────────────

MODE="standalone"
for arg in "$@"; do
    case "$arg" in
        --pytest)  MODE="pytest" ;;
        --json)    MODE="json" ;;
        --help|-h)
            echo "Usage: $0 [--pytest|--json|--help]"
            echo "  (default)  Run standalone with summary table"
            echo "  --pytest   Run via pytest -v"
            echo "  --json     Run standalone, print JSON report path"
            exit 0
            ;;
    esac
done

# ── Run ──────────────────────────────────────────────────────────────────

echo ""
echo "🔬 Producer Smoke Tests"
echo "   $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo ""

if [[ "$MODE" == "pytest" ]]; then
    exec "$VENV_PYTHON" -m pytest "$TEST_FILE" -v --tb=short -x
fi

# Standalone mode
"$VENV_PYTHON" "$TEST_FILE"
EXIT_CODE=$?

if [[ "$MODE" == "json" ]] && [[ -f /tmp/producer_smoke_results.json ]]; then
    echo ""
    echo "📋 JSON report:"
    "$VENV_PYTHON" -m json.tool /tmp/producer_smoke_results.json
fi

if [[ $EXIT_CODE -eq 0 ]]; then
    echo "🎉 All producers healthy (or gracefully skipped)"
else
    echo "⚠️  $EXIT_CODE producer(s) FAILED — see details above"
fi

exit $EXIT_CODE
