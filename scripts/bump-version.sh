#!/usr/bin/env bash
# scripts/bump-version.sh — single place to bump b1e55ed version
#
# Usage:
#   ./scripts/bump-version.sh 1.0.0-beta.7
#
# What it does:
#   1. Updates version in pyproject.toml (single source of truth)
#   2. Syncs uv.lock
#   3. Stubs a CHANGELOG.md section for the new version
#   4. Commits everything
#
# After running:
#   - Review / fill in the CHANGELOG section
#   - git push origin develop
#   - Open a release/vX.X.X PR → develop → main
#   - CI handles: tag, GitHub release, forge binary build, everything

set -euo pipefail

NEW_VERSION="${1:-}"

if [ -z "$NEW_VERSION" ]; then
  echo "Usage: $0 <version>"
  echo "  e.g. $0 1.0.0-beta.7"
  exit 1
fi

# Strip leading 'v' if provided
NEW_VERSION="${NEW_VERSION#v}"
TAG="v${NEW_VERSION}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ── Validate we're on a clean branch ─────────────────────────────────────────
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [[ "$CURRENT_BRANCH" == "main" ]]; then
  echo "❌ Don't bump version directly on main. Use develop or a release/* branch."
  exit 1
fi

if ! git diff --quiet HEAD; then
  echo "❌ Uncommitted changes. Commit or stash first."
  exit 1
fi

OLD_VERSION=$(grep '^version = ' pyproject.toml | cut -d'"' -f2)
echo "Bumping: $OLD_VERSION → $NEW_VERSION"

# ── 1. Update pyproject.toml ──────────────────────────────────────────────────
sed -i.bak "s/^version = \"${OLD_VERSION}\"/version = \"${NEW_VERSION}\"/" pyproject.toml
rm -f pyproject.toml.bak
echo "✓ pyproject.toml"

# ── 2. Sync uv.lock ───────────────────────────────────────────────────────────
uv lock --quiet 2>/dev/null || true
echo "✓ uv.lock"

# ── 3. Stub CHANGELOG.md section ─────────────────────────────────────────────
TODAY=$(date +%Y-%m-%d)
STUB="## ${TAG} — ${TODAY}

_TODO: fill in release notes_

"

# Insert stub after the first line (# Changelog header)
python3 - <<PYEOF
import re

path = "CHANGELOG.md"
try:
    content = open(path).read()
except FileNotFoundError:
    content = "# Changelog\n"

# Check if this version already has a section
if "## ${TAG}" in content:
    print("ℹ  CHANGELOG already has a section for ${TAG} — skipping stub")
else:
    # Insert after the '# Changelog' header line
    new_content = content.replace("# Changelog\n", "# Changelog\n\n${STUB}", 1)
    if new_content == content:
        # Fallback: prepend after first line
        lines = content.split("\n", 1)
        new_content = lines[0] + "\n\n${STUB}" + (lines[1] if len(lines) > 1 else "")
    open(path, "w").write(new_content)
    print("✓ CHANGELOG.md — stubbed section for ${TAG}")
PYEOF

# ── 4. Update b1e55ed-site fallback version ───────────────────────────────────
# The site fetches the latest release from GitHub API dynamically,
# but we keep a hardcoded fallback for offline/rate-limited loads.
SITE_DIR="$(cd "$REPO_ROOT/../b1e55ed-site" 2>/dev/null && pwd)" || true

if [[ -n "$SITE_DIR" && -f "$SITE_DIR/index.html" ]]; then
  sed -i.bak "s/id=\"release-version\">[^<]*/id=\"release-version\">${TAG}/" "$SITE_DIR/index.html"
  rm -f "$SITE_DIR/index.html.bak"
  echo "✓ b1e55ed-site/index.html fallback version updated"
  (cd "$SITE_DIR" && git add index.html && git commit -m "chore: bump version to ${TAG}" && git push) || \
    echo "⚠  b1e55ed-site commit/push failed — update manually"
else
  echo "ℹ  b1e55ed-site not found at ../b1e55ed-site — skipping site update"
fi

# ── 5. Commit ─────────────────────────────────────────────────────────────────
git add pyproject.toml uv.lock CHANGELOG.md
git commit -m "chore: bump version to ${TAG}"

echo ""
echo "✅ Version bumped to ${TAG}"
echo ""
echo "Next steps:"
echo "  1. Fill in CHANGELOG.md section for ${TAG}"
echo "  2. git add CHANGELOG.md && git commit --amend --no-edit"
echo "  3. git push origin ${CURRENT_BRANCH}"
echo "  4. PR ${CURRENT_BRANCH} → main (or via develop)"
echo "  5. CI creates tag, release, and forge binaries automatically"
