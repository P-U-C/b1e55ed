#!/usr/bin/env bash
# uninstall.sh — b1e55ed uninstaller
# Usage: ./uninstall.sh
#   or:  curl -sSf https://raw.githubusercontent.com/P-U-C/b1e55ed/main/uninstall.sh | bash
#
# Flags:
#   --yes         Skip all confirmations and remove everything
#   --keep-data   Remove binary/tool but preserve data and config dirs
set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
DIM='\033[2m'
RESET='\033[0m'

info()    { echo -e "${BOLD}[b1e55ed]${RESET} $*"; }
success() { echo -e "${GREEN}✓${RESET} $*"; }
skipped() { echo -e "${DIM}–${RESET} $*"; }
warn()    { echo -e "${YELLOW}⚠${RESET} $*"; }
error()   { echo -e "${RED}✗ ERROR:${RESET} $*" >&2; }

# ── Parse flags ───────────────────────────────────────────────────────────────
YES_ALL=0
KEEP_DATA=0
for arg in "$@"; do
    case "$arg" in
        --yes)       YES_ALL=1  ;;
        --keep-data) KEEP_DATA=1 ;;
        --help|-h)
            echo "Usage: ./uninstall.sh [--yes] [--keep-data]"
            echo "  --yes         Skip all confirmations"
            echo "  --keep-data   Preserve data + config directories"
            exit 0
            ;;
        *)
            warn "Unknown flag: $arg (ignored)"
            ;;
    esac
done

REMOVED=()
SKIPPED=()

# ── Confirmation helper ───────────────────────────────────────────────────────
# Usage: confirm "prompt" <default_yes|default_no>
# Returns 0 (yes) or 1 (no)
confirm() {
    local prompt="$1"
    local default="${2:-yes}"   # "yes" or "no"

    if [ "$YES_ALL" -eq 1 ]; then
        echo -e "  ${prompt} ${DIM}[auto-yes]${RESET}"
        return 0
    fi

    local hint
    if [ "$default" = "yes" ]; then
        hint="[Y/n]"
    else
        hint="[y/N]"
    fi

    local answer
    read -rp "  ${prompt} ${hint}: " answer || true
    answer="${answer:-}"

    if [ -z "$answer" ]; then
        [ "$default" = "yes" ] && return 0 || return 1
    fi
    case "${answer,,}" in
        y|yes|1) return 0 ;;
        *)        return 1 ;;
    esac
}

# ── RC-file line removal ──────────────────────────────────────────────────────
# Remove lines matching a pattern (and their preceding installer comment) from a file.
# Usage: remove_rc_lines <file> <pattern> <description>
remove_rc_lines() {
    local file="$1"
    local pattern="$2"
    local desc="$3"

    [ -f "$file" ] || return 0
    grep -qF "$pattern" "$file" 2>/dev/null || return 0

    # Use Python (if available) or sed for portable multi-line removal.
    # We need to remove both the comment marker line and the matching line.
    if command -v python3 &>/dev/null; then
        python3 - "$file" "$pattern" <<'PYEOF'
import sys, pathlib

path = pathlib.Path(sys.argv[1])
pattern = sys.argv[2]
marker = "# Added by b1e55ed installer"

lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
new_lines = []
skip_next = False
for i, line in enumerate(lines):
    if skip_next:
        skip_next = False
        continue
    stripped = line.rstrip()
    if stripped == marker and i + 1 < len(lines):
        next_stripped = lines[i + 1].rstrip()
        if pattern in next_stripped:
            skip_next = True
            continue
    if pattern in stripped:
        continue
    new_lines.append(line)

path.write_text("".join(new_lines), encoding="utf-8")
PYEOF
    else
        # Fallback: plain sed (removes matching lines, not the comment)
        sed -i "/$pattern/d" "$file" 2>/dev/null || true
    fi

    success "Removed ${desc} from ${file}"
}

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║         b1e55ed uninstaller              ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""
if [ "$YES_ALL" -eq 1 ]; then
    warn "--yes mode: all confirmations will be auto-accepted."
fi
if [ "$KEEP_DATA" -eq 1 ]; then
    warn "--keep-data mode: data and config directories will be preserved."
fi
echo ""

# ── Step 1: Check if b1e55ed binary exists ───────────────────────────────────
info "[1/5] Checking for b1e55ed binary..."
echo ""

LOCAL_BIN="$HOME/.local/bin"
B1E55ED_BIN="${LOCAL_BIN}/b1e55ed"

if command -v b1e55ed &>/dev/null; then
    B1E55ED_PATH="$(command -v b1e55ed)"
    success "b1e55ed found at: ${B1E55ED_PATH}"
elif [ -f "$B1E55ED_BIN" ]; then
    B1E55ED_PATH="$B1E55ED_BIN"
    success "b1e55ed found at: ${B1E55ED_BIN}"
else
    skipped "b1e55ed binary not found in PATH or ~/.local/bin"
    B1E55ED_PATH=""
fi
echo ""

# ── Step 2: uv tool uninstall ─────────────────────────────────────────────────
info "[2/5] uv tool uninstall..."
echo ""

if command -v uv &>/dev/null; then
    if confirm "Remove b1e55ed uv tool installation? (runs: uv tool uninstall b1e55ed)" "yes"; then
        if uv tool uninstall b1e55ed 2>&1; then
            success "uv tool uninstall succeeded"
            REMOVED+=("uv tool (b1e55ed)")
        else
            warn "uv tool uninstall failed (may not be installed as a uv tool — continuing)"
            SKIPPED+=("uv tool uninstall (not installed or error)")
        fi
    else
        skipped "uv tool uninstall skipped by user"
        SKIPPED+=("uv tool uninstall (skipped)")
    fi
else
    skipped "uv not found in PATH — skipping uv tool uninstall"
    SKIPPED+=("uv tool uninstall (uv not found)")
fi
echo ""

# ── Step 3: Remove ~/.local/bin/b1e55ed ──────────────────────────────────────
info "[3/5] Remove binary..."
echo ""

if [ -f "$B1E55ED_BIN" ]; then
    if confirm "Remove binary at ${B1E55ED_BIN}?" "yes"; then
        rm -f "$B1E55ED_BIN"
        success "Removed ${B1E55ED_BIN}"
        REMOVED+=("~/.local/bin/b1e55ed")
    else
        skipped "Binary not removed (kept at ${B1E55ED_BIN})"
        SKIPPED+=("binary (~/.local/bin/b1e55ed)")
    fi
else
    skipped "~/.local/bin/b1e55ed not found (already removed)"
    SKIPPED+=("binary (not found)")
fi
echo ""

# ── Step 4: Remove data / config dirs ─────────────────────────────────────────
info "[4/5] Data and config directories..."
echo ""

if [ "$KEEP_DATA" -eq 1 ]; then
    skipped "--keep-data: preserving all data and config directories"
    SKIPPED+=("data + config dirs (--keep-data)")
else
    # ~/.local/share/b1e55ed
    XDG_DATA="${HOME}/.local/share/b1e55ed"
    if [ -d "$XDG_DATA" ]; then
        if confirm "Remove local data dir at ${XDG_DATA}?" "no"; then
            rm -rf "$XDG_DATA"
            success "Removed ${XDG_DATA}"
            REMOVED+=("~/.local/share/b1e55ed")
        else
            skipped "Data dir kept at ${XDG_DATA}"
            SKIPPED+=("~/.local/share/b1e55ed (skipped)")
        fi
    else
        skipped "~/.local/share/b1e55ed not found"
    fi

    # ~/.config/b1e55ed
    XDG_CONFIG="${HOME}/.config/b1e55ed"
    if [ -d "$XDG_CONFIG" ]; then
        if confirm "Remove config dir at ${XDG_CONFIG}?" "no"; then
            rm -rf "$XDG_CONFIG"
            success "Removed ${XDG_CONFIG}"
            REMOVED+=("~/.config/b1e55ed")
        else
            skipped "Config dir kept at ${XDG_CONFIG}"
            SKIPPED+=("~/.config/b1e55ed (skipped)")
        fi
    else
        skipped "~/.config/b1e55ed not found"
    fi

    # If running from inside the repo, ask about data/ and .b1e55ed/
    if [ -f "pyproject.toml" ] && grep -q 'b1e55ed' pyproject.toml 2>/dev/null; then
        REPO_DATA="$(pwd)/data"
        REPO_CONFIG="$(pwd)/.b1e55ed"

        if [ -d "$REPO_DATA" ]; then
            if confirm "Remove repo data dir at ${REPO_DATA}?" "no"; then
                rm -rf "$REPO_DATA"
                success "Removed ${REPO_DATA}"
                REMOVED+=("$(pwd)/data")
            else
                skipped "Repo data dir kept at ${REPO_DATA}"
                SKIPPED+=("$(pwd)/data (skipped)")
            fi
        fi

        if [ -d "$REPO_CONFIG" ]; then
            if confirm "Remove repo identity/config dir at ${REPO_CONFIG}?" "no"; then
                rm -rf "$REPO_CONFIG"
                success "Removed ${REPO_CONFIG}"
                REMOVED+=("$(pwd)/.b1e55ed")
            else
                skipped "Repo config dir kept at ${REPO_CONFIG}"
                SKIPPED+=("$(pwd)/.b1e55ed (skipped)")
            fi
        fi
    fi
fi
echo ""

# ── Step 5: Remove shell rc additions ────────────────────────────────────────
info "[5/5] Shell RC cleanup..."
echo ""

RC_FILES=("$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.bash_profile")
PATH_PATTERN=".local/bin"
PW_PATTERN="B1E55ED_MASTER_PASSWORD"

any_rc_changed=0
for rc in "${RC_FILES[@]}"; do
    [ -f "$rc" ] || continue

    # PATH export lines
    if grep -qF "$PATH_PATTERN" "$rc" 2>/dev/null; then
        if confirm "Remove ~/.local/bin PATH line from ${rc}?" "yes"; then
            remove_rc_lines "$rc" "$PATH_PATTERN" "PATH export"
            REMOVED+=("PATH line in ${rc}")
            any_rc_changed=1
        else
            skipped "PATH line kept in ${rc}"
            SKIPPED+=("PATH line in ${rc}")
        fi
    fi

    # B1E55ED_MASTER_PASSWORD lines
    if grep -qF "$PW_PATTERN" "$rc" 2>/dev/null; then
        if confirm "Remove B1E55ED_MASTER_PASSWORD export from ${rc}?" "yes"; then
            remove_rc_lines "$rc" "$PW_PATTERN" "B1E55ED_MASTER_PASSWORD export"
            REMOVED+=("B1E55ED_MASTER_PASSWORD in ${rc}")
            any_rc_changed=1
        else
            skipped "B1E55ED_MASTER_PASSWORD kept in ${rc}"
            SKIPPED+=("B1E55ED_MASTER_PASSWORD in ${rc}")
        fi
    fi
done

if [ "$any_rc_changed" -eq 0 ]; then
    skipped "No shell rc additions found to remove"
fi
echo ""

# ── Summary ───────────────────────────────────────────────────────────────────
echo -e "${GREEN}══════════════════════════════════════════${RESET}"
echo ""

if [ "${#REMOVED[@]}" -gt 0 ]; then
    echo -e "${BOLD}Removed:${RESET}"
    for item in "${REMOVED[@]}"; do
        echo -e "  ${GREEN}✓${RESET} ${item}"
    done
    echo ""
fi

if [ "${#SKIPPED[@]}" -gt 0 ]; then
    echo -e "${BOLD}Skipped / not found:${RESET}"
    for item in "${SKIPPED[@]}"; do
        echo -e "  ${DIM}–${RESET} ${item}"
    done
    echo ""
fi

if [ "${#REMOVED[@]}" -gt 0 ]; then
    echo -e "${GREEN}${BOLD}Uninstall complete.${RESET} b1e55ed has been removed."
else
    echo -e "${YELLOW}Uninstall finished with no changes.${RESET}"
fi
echo ""
echo -e "${GREEN}══════════════════════════════════════════${RESET}"
echo ""
