#!/usr/bin/env bash
# Pre-commit hook — validates documentation dependency graph.
# Install once with: bash scripts/install-hooks.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "$SCRIPT_DIR/validate_doc_deps.sh"
