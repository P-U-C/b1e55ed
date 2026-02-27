#!/usr/bin/env bash
# install.sh — b1e55ed installer
# Usage: curl -sSf https://raw.githubusercontent.com/P-U-C/b1e55ed/main/install.sh | bash
# Or:    ./install.sh
#
# Test from a specific branch (e.g. develop):
#   curl -sSf https://raw.githubusercontent.com/P-U-C/b1e55ed/main/install.sh | BRANCH=develop bash
#   NOTE: BRANCH=... must prefix 'bash', not 'curl' — env vars only apply to the command they prefix.
#
# Idempotent: safe to re-run.
set -euo pipefail

# Branch to install from — pinned to main so changing the default branch
# on GitHub doesn't accidentally install from develop.
BRANCH="${BRANCH:-main}"

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
RESET='\033[0m'

info()    { echo -e "${BOLD}[b1e55ed]${RESET} $*"; }
success() { echo -e "${GREEN}✓${RESET} $*"; }
warn()    { echo -e "${YELLOW}⚠${RESET} $*"; }
error()   { echo -e "${RED}✗ ERROR:${RESET} $*" >&2; }

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║         b1e55ed installer                ║"
echo "  ║   contributor intelligence engine        ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""

# ── Step 1: Check Python 3.11+ ────────────────────────────────────────────────
info "Checking Python version..."

PYTHON_BIN=""
for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" &>/dev/null; then
        version=$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [ "$major" -gt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -ge 11 ]; }; then
            PYTHON_BIN="$candidate"
            success "Python $version found ($PYTHON_BIN)"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    # Try to bootstrap Python via uv (works even without Homebrew)
    if command -v uv &>/dev/null || [[ "$OSTYPE" == "darwin"* ]]; then
        # Install uv first if needed on macOS
        if ! command -v uv &>/dev/null; then
            info "No Python found — installing uv to bootstrap Python..."
            curl -LsSf https://astral.sh/uv/install.sh | sh
            export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
        fi
        if command -v uv &>/dev/null; then
            info "No Python found — bootstrapping via uv..."
            uv python install 3.13 || uv python install 3.12 || true
            # Re-probe standard candidates
            for candidate in python3.13 python3.12 python3.11; do
                if command -v "$candidate" &>/dev/null 2>/dev/null; then
                    version=$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
                    major=$(echo "$version" | cut -d. -f1)
                    minor=$(echo "$version" | cut -d. -f2)
                    if [ "$major" -gt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -ge 11 ]; }; then
                        PYTHON_BIN="$candidate"
                        success "Python $version found via bootstrap ($PYTHON_BIN)"
                        break
                    fi
                fi
            done
            # Also try uv's managed Python path directly
            if [ -z "$PYTHON_BIN" ]; then
                UV_PYTHON=$(uv python find 3.13 2>/dev/null || uv python find 3.12 2>/dev/null || uv python find 3.11 2>/dev/null || true)
                if [ -n "$UV_PYTHON" ]; then
                    version=$("$UV_PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
                    major=$(echo "$version" | cut -d. -f1)
                    minor=$(echo "$version" | cut -d. -f2)
                    if [ "$major" -gt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -ge 11 ]; }; then
                        PYTHON_BIN="$UV_PYTHON"
                        success "Python $version found via uv managed path ($PYTHON_BIN)"
                    fi
                fi
            fi
        fi
    fi
fi

if [ -z "$PYTHON_BIN" ]; then
    error "Python 3.11+ is required but not found."
    echo ""
    echo "  Install Python 3.11+ for your OS:"
    echo ""

    # Detect OS for install instructions
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "  macOS (Homebrew or uv):"
        echo "    brew install python@3.11"
        echo "    # or:"
        echo "    uv python install 3.13"
    elif [ -f /etc/debian_version ]; then
        echo "  Ubuntu/Debian:"
        echo "    sudo apt update && sudo apt install python3.11 python3.11-venv"
    elif [ -f /etc/redhat-release ]; then
        echo "  RHEL/CentOS/Fedora:"
        echo "    sudo dnf install python3.11"
    elif [[ "$OSTYPE" == "msys"* ]] || [[ "$OSTYPE" == "cygwin"* ]]; then
        echo "  Windows (winget):"
        echo "    winget install Python.Python.3.11"
    else
        echo "  Download from: https://www.python.org/downloads/"
    fi
    echo ""
    echo "  Then re-run this installer."
    exit 1
fi

# ── Step 2: Install uv ────────────────────────────────────────────────────────
info "Checking for uv..."

if command -v uv &>/dev/null; then
    UV_VERSION=$(uv --version 2>&1 | head -1)
    success "uv already installed: $UV_VERSION"
else
    info "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Reload PATH so we can find uv immediately
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    if command -v uv &>/dev/null; then
        UV_VERSION=$(uv --version 2>&1 | head -1)
        success "uv installed: $UV_VERSION"
    else
        error "uv installation failed. Please install manually: https://github.com/astral-sh/uv"
        exit 1
    fi
fi

# ── Step 3: Install b1e55ed as a uv tool ──────────────────────────────────────
info "Installing b1e55ed..."

# If running from a pipe (curl|bash), we need the repo. Check if we're already in it.
if [ -f "pyproject.toml" ] && grep -q 'b1e55ed' pyproject.toml 2>/dev/null; then
    REPO_DIR="$(pwd)"
    info "Installing from local repo: $REPO_DIR"
    if uv tool install --editable . 2>/dev/null; then
        success "b1e55ed installed as a uv tool (editable)"
    else
        warn "uv tool install failed, falling back to uv sync..."
        uv sync
        success "b1e55ed dependencies synced (use ./b1e55ed or uv run b1e55ed)"
    fi
else
    # Install from GitHub — always explicit branch (never relies on default branch)
    INSTALL_URL="git+https://github.com/P-U-C/b1e55ed.git@${BRANCH}"
    info "Installing from: $INSTALL_URL"
    if uv tool install --refresh "$INSTALL_URL" 2>/dev/null; then
        success "b1e55ed installed as a uv tool"
    else
        error "Installation failed. Clone the repo and run ./install.sh from inside it."
        exit 1
    fi
fi

# ── Step 4: Add ~/.local/bin to PATH ─────────────────────────────────────────
LOCAL_BIN="$HOME/.local/bin"
info "Checking PATH for $LOCAL_BIN..."

add_to_path() {
    local rc_file="$1"
    local export_line='export PATH="$HOME/.local/bin:$PATH"'
    if [ -f "$rc_file" ]; then
        if grep -qF '.local/bin' "$rc_file" 2>/dev/null; then
            success "$rc_file already has ~/.local/bin in PATH"
        else
            echo "" >> "$rc_file"
            echo "# Added by b1e55ed installer" >> "$rc_file"
            echo "$export_line" >> "$rc_file"
            success "Added ~/.local/bin to PATH in $rc_file"
        fi
    fi
}

# Detect which shell rc files exist
if [[ "$SHELL" == *"zsh"* ]] || [ -f "$HOME/.zshrc" ]; then
    add_to_path "$HOME/.zshrc"
fi
if [[ "$SHELL" == *"bash"* ]] || [ -f "$HOME/.bashrc" ]; then
    add_to_path "$HOME/.bashrc"
fi
if [ -f "$HOME/.bash_profile" ]; then
    add_to_path "$HOME/.bash_profile"
fi
if [[ "$SHELL" == *"fish"* ]] || [ -f "$HOME/.config/fish/config.fish" ]; then
    FISH_CONFIG="$HOME/.config/fish/config.fish"
    FISH_LINE='fish_add_path "$HOME/.local/bin"'
    if [ -f "$FISH_CONFIG" ]; then
        if grep -qF '.local/bin' "$FISH_CONFIG" 2>/dev/null; then
            success "$FISH_CONFIG already has ~/.local/bin in PATH"
        else
            echo "" >> "$FISH_CONFIG"
            echo "# Added by b1e55ed installer" >> "$FISH_CONFIG"
            echo "$FISH_LINE" >> "$FISH_CONFIG"
            success "Added ~/.local/bin to fish PATH in $FISH_CONFIG"
        fi
    fi
fi

# Ensure it's in PATH for this session
export PATH="$LOCAL_BIN:$PATH"

# ── Step 5: Verify install ────────────────────────────────────────────────────
info "Verifying installation..."

if command -v b1e55ed &>/dev/null; then
    B1E55ED_VERSION=$(b1e55ed --version 2>&1 | head -1)
    success "b1e55ed is available: $B1E55ED_VERSION"
elif [ -f "$LOCAL_BIN/b1e55ed" ]; then
    B1E55ED_VERSION=$("$LOCAL_BIN/b1e55ed" --version 2>&1 | head -1)
    success "b1e55ed installed at $LOCAL_BIN/b1e55ed: $B1E55ED_VERSION"
else
    warn "b1e55ed binary not found in PATH yet."
    echo "  You may need to restart your shell or run:"
    echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

# ── Step 6: Download Rust forge binary ────────────────────────────────────────
info "Downloading Rust forge binary..."

FORGE_DIR="$HOME/.local/share/b1e55ed/bin"
mkdir -p "$FORGE_DIR"

# Resolve latest release tag (including pre-releases — /releases/latest skips them)
RELEASE_TAG=$(curl -fsSL "https://api.github.com/repos/P-U-C/b1e55ed/releases?per_page=1" 2>/dev/null \
    | python3 -c "import sys,json; r=json.load(sys.stdin); print(r[0]['tag_name'])" 2>/dev/null || echo "")

# Detect platform
FORGE_URL=""
if [ -n "$RELEASE_TAG" ]; then
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # Universal binary — works on both Apple Silicon and Intel
        FORGE_URL="https://github.com/P-U-C/b1e55ed/releases/download/${RELEASE_TAG}/b1e55ed-forge-macos"
    elif [[ "$OSTYPE" == "linux"* ]]; then
        ARCH=$(uname -m)
        if [[ "$ARCH" == "x86_64" ]]; then
            FORGE_URL="https://github.com/P-U-C/b1e55ed/releases/download/${RELEASE_TAG}/b1e55ed-forge-linux-x86_64"
        fi
    fi
fi

if [ -n "$FORGE_URL" ]; then
    if curl -fsSL "$FORGE_URL" -o "$FORGE_DIR/b1e55ed-forge" 2>/dev/null; then
        chmod +x "$FORGE_DIR/b1e55ed-forge"
        # macOS: clear quarantine bit so Gatekeeper doesn't block execution
        if [[ "$OSTYPE" == "darwin"* ]]; then
            xattr -dr com.apple.quarantine "$FORGE_DIR/b1e55ed-forge" 2>/dev/null || true
        fi
        success "Rust forge binary installed (much faster than Python fallback)"
    else
        warn "Could not download forge binary (no release yet) — Python fallback will be used"
        warn "Run 'b1e55ed identity forge' after a release is published, or use random identity"
    fi
else
    warn "No forge binary available for this platform — use 'b1e55ed identity forge' with Python fallback or random identity"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}══════════════════════════════════════════${RESET}"
echo -e "${GREEN}  Installation complete!${RESET}"
echo ""
echo "  Next step:"
echo ""
echo -e "    ${BOLD}b1e55ed wizard${RESET}"
echo ""
echo "  Or reload your shell first if b1e55ed isn't found:"
echo "    source ~/.bashrc    # bash"
echo "    source ~/.zshrc     # zsh"
echo "    exec fish           # fish"
echo -e "${GREEN}══════════════════════════════════════════${RESET}"
echo ""
