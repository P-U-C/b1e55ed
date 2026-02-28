#!/usr/bin/env bash
set -uo pipefail  # Removed -e to handle grep failures gracefully

# Validate documentation dependency graph matches actual cross-references.
#
# Checks:
# 1. All .md files are reachable from README.md (no orphans)
# 2. No broken internal links
# 3. dependencies-docs.md is up to date (all references documented)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

errors=0

echo "🔍 Validating documentation dependencies..."

# 1. Find all markdown + MDX files
all_docs=$(find docs samples -name "*.md" -type f 2>/dev/null | sort)
all_mdx=$(find docs -name "*.mdx" -type f 2>/dev/null | sort)
all_docs="$all_docs"$'\n'"$all_mdx"
all_docs="$all_docs"$'\n'"README.md"
all_docs="$all_docs"$'\n'"DOCKER.md"
all_docs="$all_docs"$'\n'"ROADMAP.md"

# 2. Check for orphaned docs (not referenced anywhere)
echo ""
echo "Checking for orphaned documentation..."
orphans=0

for doc in $all_docs; do
  # Skip dependencies-docs.md (references everything by definition)
  if [[ "$doc" == "docs/dependencies-docs.md" ]]; then
    continue
  fi
  
  basename=$(basename "$doc")
  
  # Check if referenced in any other doc (*.md or *.mdx)
  if ! grep -r "$basename" docs samples README.md DOCKER.md ROADMAP.md --include="*.md" --include="*.mdx" 2>/dev/null | grep -v "^$doc:" | grep -q .; then
    # Allow README.md to be unreferenced (it's the entry point)
    if [[ "$doc" != "README.md" ]]; then
      echo "  ❌ ORPHANED: $doc (not referenced by any other doc)"
      orphans=$((orphans + 1))
      errors=$((errors + 1))
    fi
  fi
done

if [[ $orphans -eq 0 ]]; then
  echo "  ✅ No orphaned docs (all reachable from README.md)"
fi

# 3. Check for broken internal links
echo ""
echo "Checking for broken internal links..."
broken_links_file=$(mktemp)

for doc in $all_docs; do
  if [[ ! -f "$doc" ]]; then
    continue
  fi
  
  # Extract markdown links: [text](path.md) or [text](path.mdx)
  # Also handle [text](docs/path.md), [text](../path.md), etc.
  # Skip code blocks (lines starting with ``` or    )
  grep -v '^\(```\|    \|#\)' "$doc" 2>/dev/null | grep -o '\[.*\]([^)]*\.mdx\{0,1\}[^)]*)' 2>/dev/null | while IFS= read -r link; do
    # Extract path from [text](path)
    path=$(echo "$link" | sed 's/.*(\([^)]*\))/\1/')
    path="${path%%#*}"  # Strip #fragment anchors before file existence check
    
    # Resolve relative paths
    if [[ "$path" == ../* ]]; then
      # Go up one directory
      dir=$(dirname "$doc")
      resolved="$dir/$path"
    elif [[ "$path" == docs/* ]] || [[ "$path" == samples/* ]]; then
      # Absolute from repo root
      resolved="$path"
    else
      # Relative to doc's directory
      dir=$(dirname "$doc")
      resolved="$dir/$path"
    fi
    
    # Normalize path (remove ../, ./, etc.)
    resolved=$(realpath -m "$resolved" 2>/dev/null || echo "$resolved")
    
    # Check if file exists
    if [[ ! -f "$resolved" ]]; then
      echo "BROKEN: $doc → $path (resolved: $resolved)" >> "$broken_links_file"
    fi
  done
done

if [[ -s "$broken_links_file" ]]; then
  while IFS= read -r line; do
    echo "  ❌ $line"
    errors=$((errors + 1))
  done < "$broken_links_file"
  rm -f "$broken_links_file"
else
  echo "  ✅ No broken internal links"
  rm -f "$broken_links_file"
fi

# 4. Check if dependencies-docs.md needs updating
echo ""
echo "Checking if dependencies-docs.md is up to date..."
deps_doc="docs/dependencies-docs.md"

if [[ ! -f "$deps_doc" ]]; then
  echo "  ❌ MISSING: docs/dependencies-docs.md not found"
  errors=$((errors + 1))
else
  # Extract all docs mentioned in dependencies-docs.md (*.md and *.mdx)
  declared_docs=$(grep -o '[a-zA-Z0-9_/-]\+\.mdx\{0,1\}' "$deps_doc" 2>/dev/null | sort -u || true)
  
  # Compare with actual docs
  undocumented=0
  for doc in $all_docs; do
    if ! echo "$declared_docs" | grep -q "$(basename "$doc")"; then
      echo "  ⚠️  UNDOCUMENTED: $doc not mentioned in dependencies-docs.md"
      undocumented=$((undocumented + 1))
      # Don't fail on this (warning only)
    fi
  done
  
  if [[ $undocumented -eq 0 ]]; then
    echo "  ✅ dependencies-docs.md is up to date"
  else
    echo "  ⚠️  $undocumented doc(s) not mentioned in dependencies-docs.md (warnings only)"
  fi
fi

# Summary
echo ""
if [[ $errors -eq 0 ]]; then
  echo "✅ Documentation dependency validation passed"
  echo "   Checked $(echo "$all_docs" | wc -l) documentation files"
  exit 0
else
  echo "❌ Documentation dependency validation failed"
  echo "   $errors error(s) found"
  exit 1
fi
