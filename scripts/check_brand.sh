#!/bin/bash
# Brand vocabulary enforcement for b1e55ed documentation
# Based on SOUL.md guidelines

set -e

DOCS_DIR="${1:-docs}"
ERRORS=0

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "Checking brand vocabulary in $DOCS_DIR..."

# Banned crypto-twitter vernacular
BANNED_TERMS=(
    "wagmi"
    "ser"
    "gm"
    "LFG"
    "fren"
    "frens"
    "ngmi"
    "wen"
    "hodl"
    "based"
    "gigabrain"
)

# Banned corporate speak
CORPORATE_SPEAK=(
    "Great question"
    "I'd be happy to"
    "Absolutely"
    "Amazing"
    "Awesome"
    "Let's dive in"
    "At the end of the day"
)

# Check for banned terms (exclude legitimate uses of "based")
for term in "${BANNED_TERMS[@]}"; do
    if [ "$term" = "based" ]; then
        # Only flag standalone "based" (not "based on", "file-based", etc.)
        if grep -r -i "\bbased\b" "$DOCS_DIR" --include="*.md" 2>/dev/null | grep -v "based on" | grep -v "\-based"; then
            echo -e "${RED}✗${NC} Found banned CT term: ${term}"
            ERRORS=$((ERRORS + 1))
        fi
    else
        if grep -r -i "\b${term}\b" "$DOCS_DIR" --include="*.md" 2>/dev/null; then
            echo -e "${RED}✗${NC} Found banned CT term: ${term}"
            ERRORS=$((ERRORS + 1))
        fi
    fi
done

# Check for corporate speak
for phrase in "${CORPORATE_SPEAK[@]}"; do
    if grep -r -i "${phrase}" "$DOCS_DIR" --include="*.md" 2>/dev/null; then
        echo -e "${RED}✗${NC} Found corporate speak: ${phrase}"
        ERRORS=$((ERRORS + 1))
    fi
done

# Check for excessive exclamation marks (>2 in a paragraph)
while IFS= read -r file; do
    # Count exclamation marks per paragraph (blank-line separated)
    awk '
        BEGIN { count = 0; para_num = 0 }
        /^$/ { 
            if (count > 2) {
                print FILENAME ":" para_num ": Too many exclamation marks (" count ")"
                exit 1
            }
            count = 0
            para_num++
        }
        { count += gsub(/!/, "!") }
        END { 
            if (count > 2) {
                print FILENAME ":" para_num ": Too many exclamation marks (" count ")"
                exit 1
            }
        }
    ' FILENAME="$file" "$file" || {
        echo -e "${YELLOW}⚠${NC}  Excessive exclamation marks in: $file"
    }
done < <(find "$DOCS_DIR" -name "*.md")

# Check for "very" (weak intensifier)
if grep -r -i "\bvery\b" "$DOCS_DIR" --include="*.md" 2>/dev/null | head -5; then
    echo -e "${YELLOW}⚠${NC}  Consider removing 'very' (weak intensifier)"
fi

# Positive checks
echo ""
echo "Positive brand signals:"

# Direct, bottom-line-first (check if docs start with action or result)
GOOD=0
for file in "$DOCS_DIR"/*.md; do
    [ -f "$file" ] || continue
    
    # Check first non-blank, non-heading line
    first_line=$(grep -v "^#" "$file" | grep -v "^$" | head -1)
    
    # Good patterns: starts with verb, direct statement, or code block
    if echo "$first_line" | grep -qE "^(Install|Configure|Run|Build|Deploy|Create|Set|Use|Enable|Start|Stop|\`\`\`|>)"; then
        GOOD=$((GOOD + 1))
    fi
done

total_docs=$(find "$DOCS_DIR" -name "*.md" | wc -l)
echo -e "  ${GREEN}✓${NC} $GOOD/$total_docs docs start direct/action-first"

# Check for clear section structure
for file in "$DOCS_DIR"/*.md; do
    [ -f "$file" ] || continue
    
    # Count headings
    headings=$(grep -c "^#" "$file" || true)
    if [ "$headings" -ge 3 ]; then
        echo -e "  ${GREEN}✓${NC} $(basename "$file"): Well-structured ($headings sections)"
    fi
done

echo ""

if [ $ERRORS -gt 0 ]; then
    echo -e "${RED}✗ Found $ERRORS brand violations${NC}"
    exit 1
else
    echo -e "${GREEN}✓ No brand violations found${NC}"
    exit 0
fi
