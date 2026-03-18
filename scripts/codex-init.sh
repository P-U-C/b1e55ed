#!/usr/bin/env bash
# codex-init.sh — Run at the start of every Codex task session.
# Establishes a clean baseline before any code changes.
# Usage: bash scripts/codex-init.sh [branch-name]
#
# Exits non-zero if baseline is broken — stop and report, don't proceed.

set -euo pipefail

BRANCH="${1:-}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== codex-init ==="
echo "Working directory: $REPO_ROOT"
echo ""

# 1. Git state
echo "--- git status ---"
git status --short
echo ""
echo "--- recent commits ---"
git log --oneline -5
echo ""

# 2. Branch setup
if [[ -n "$BRANCH" ]]; then
  echo "--- setting up branch: $BRANCH ---"
  git fetch origin
  if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    git checkout "$BRANCH"
    git pull origin "$BRANCH" 2>/dev/null || true
  else
    git checkout -b "$BRANCH" origin/develop
  fi
  echo "On branch: $(git branch --show-current)"
  echo ""
fi

# 3. Baseline test run
echo "--- baseline tests (pre-existing failures expected: 7 trio/async) ---"
python3 -m pytest --tb=no -q 2>&1 | tail -5
PYTEST_EXIT=${PIPESTATUS[0]}

# Count failures
FAIL_COUNT=$(python3 -m pytest --tb=no -q 2>&1 | grep -c "FAILED" || true)

echo ""
if [[ $FAIL_COUNT -le 7 ]]; then
  echo "BASELINE OK — $FAIL_COUNT pre-existing failures (expected <= 7)"
else
  echo "BASELINE BROKEN — $FAIL_COUNT failures found (expected <= 7)"
  echo "Stop. Do not write any code. Report the failing tests."
  exit 1
fi

# 4. Ruff check
echo ""
echo "--- ruff check ---"
ruff check engine/ tests/ && echo "RUFF CLEAN"

echo ""
echo "=== codex-init complete. Safe to proceed. ==="
