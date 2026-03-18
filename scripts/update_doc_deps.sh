#!/usr/bin/env bash
# Auto-update docs/dependencies-docs.md with undocumented markdown files.
#
# Scans docs/*.md (and docs/internal/*.md) and adds any file not yet
# mentioned in dependencies-docs.md to the Additional Documentation table.
# Existing content is never modified.
#
# Usage:
#   bash scripts/update_doc_deps.sh [--check]   # --check exits 1 if changes needed

set -euo pipefail

DEPS_FILE="docs/dependencies-docs.md"
CHECK_ONLY=false

for arg in "$@"; do
  if [ "$arg" = "--check" ]; then
    CHECK_ONLY=true
  fi
done

# Collect all markdown files in docs/ (excluding the deps file itself and internal/)
all_docs=()
while IFS= read -r -d '' f; do
  all_docs+=("$f")
done < <(find docs -maxdepth 2 -name "*.md" ! -name "dependencies-docs.md" -print0 | sort -z)

missing=()

for doc in "${all_docs[@]}"; do
  basename=$(basename "$doc")
  # Check if referenced anywhere in the deps file
  if ! grep -q "$basename" "$DEPS_FILE" 2>/dev/null; then
    missing+=("$doc")
  fi
done

if [ ${#missing[@]} -eq 0 ]; then
  echo "✅ All docs referenced in $DEPS_FILE"
  exit 0
fi

echo "⚠️  ${#missing[@]} undocumented doc(s) found:"
for doc in "${missing[@]}"; do
  echo "   $doc"
done

if [ "$CHECK_ONLY" = true ]; then
  echo ""
  echo "Run \`bash scripts/update_doc_deps.sh\` to append them."
  exit 1
fi

# Append missing docs to the Additional Documentation table
# Find the last table row and insert after it, before the *Last updated* line

tmp=$(mktemp)
cp "$DEPS_FILE" "$tmp"

for doc in "${missing[@]}"; do
  basename=$(basename "$doc")
  name="${basename%.md}"
  # Insert new table row before the *Last updated* line
  sed -i "/^\*Last updated/i \| [$basename]($doc) \| Auto-detected — add description |" "$DEPS_FILE"
done

# Update the "Last updated" date
today=$(date -u +%Y-%m-%d)
sed -i "s|\*Last updated:.*\*|\*Last updated: $today\*|" "$DEPS_FILE"

echo "✅ Added ${#missing[@]} doc(s) to $DEPS_FILE"
