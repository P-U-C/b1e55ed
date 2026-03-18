#!/usr/bin/env bash
# scripts/smoke_test_doctor.sh — Run all 5 doctor tiers and output a report.
#
# Usage:
#   ./scripts/smoke_test_doctor.sh            # human-readable
#   ./scripts/smoke_test_doctor.sh --json     # machine-readable
#   ./scripts/smoke_test_doctor.sh --tier 2   # offline only (CI-safe)
#
# Exit codes:
#   0 = all pass (no fails)
#   1 = at least one fail
#   2 = script error

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Detect venv
if [[ -f .venv/bin/python ]]; then
    PYTHON=".venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
else
    echo "ERROR: No Python found. Activate venv or install Python 3.11+."
    exit 2
fi

# Parse args
TIER="${1:---tier}"
if [[ "$TIER" == "--tier" ]]; then
    TIER_VALUE="${2:-4}"
    shift 2 2>/dev/null || true
elif [[ "$TIER" == "--json" ]]; then
    # --json without --tier means run all tiers
    TIER_VALUE="4"
else
    TIER_VALUE="4"
fi

JSON_FLAG=""
for arg in "$@"; do
    if [[ "$arg" == "--json" ]]; then
        JSON_FLAG="--json"
    fi
done

# If first arg was --json, include it
if [[ "${1:-}" == "--json" ]]; then
    JSON_FLAG="--json"
fi

echo "╔══════════════════════════════════════════════╗"
echo "║         b1e55ed doctor smoke test            ║"
echo "╠══════════════════════════════════════════════╣"
echo "║  Tier: ${TIER_VALUE}  Python: $($PYTHON --version 2>&1)  ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# Run doctor
set +e
$PYTHON -m engine.cli.main doctor --tier "$TIER_VALUE" $JSON_FLAG 2>/dev/null
EXIT_CODE=$?
set -e

echo ""
if [[ $EXIT_CODE -eq 0 ]]; then
    echo "✅ SMOKE TEST PASSED"
else
    echo "❌ SMOKE TEST FAILED (exit code: $EXIT_CODE)"
fi

exit $EXIT_CODE
