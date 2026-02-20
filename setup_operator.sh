#!/usr/bin/env bash
set -euo pipefail

echo "=== b1e55ed operator setup ==="

# Check Python
python3 -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ required'" || {
    echo "ERROR: Python 3.11+ required"; exit 1
}

# Install deps
if command -v uv &>/dev/null; then
    uv sync --all-extras
else
    pip install -e ".[all]"
fi

# Run setup
if [ -t 0 ]; then
    python3 -m engine.cli setup
else
    python3 -m engine.cli setup --non-interactive
fi

echo "=== Setup complete. Run: b1e55ed brain ==="
