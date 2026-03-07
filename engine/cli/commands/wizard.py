"""engine.cli.commands.wizard

Interactive setup wizard for b1e55ed contributors.

Design constraints:
- stdlib only (no rich, no questionary, no external deps)
- ANSI color codes with TTY detection fallback
- Never crashes on subprocess failure — always catches and continues
"""

from __future__ import annotations

import argparse
import os
import secrets
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from engine.core.paths import b1e55ed_dir, logs_dir

if TYPE_CHECKING:
    from engine.cli.main import CliContext

# ── ANSI helpers ─────────────────────────────────────────────────────────────

IS_TTY = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    """Wrap text in an ANSI code, or return plain text if not a TTY."""
    if not IS_TTY:
        return text
    return f"\033[{code}m{text}\033[0m"


def bold(t: str) -> str:
    return _c("1", t)


def green(t: str) -> str:
    return _c("0;32", t)


def yellow(t: str) -> str:
    return _c("1;33", t)


def red(t: str) -> str:
    return _c("0;31", t)


def cyan(t: str) -> str:
    return _c("0;36", t)


def dim(t: str) -> str:
    return _c("2", t)


def _ok(msg: str = "") -> str:
    return green("✓") + (f" {msg}" if msg else "")


def _fail(msg: str = "") -> str:
    return red("✗") + (f" {msg}" if msg else "")


def _ask(prompt: str, default: str = "") -> str:
    """Prompt the user, return stripped input or default."""
    if default:
        full_prompt = f"{prompt} [{dim(default)}]: "
    else:
        full_prompt = f"{prompt}: "
    try:
        raw = input(full_prompt).strip()
        return raw if raw else default
    except (EOFError, KeyboardInterrupt):
        print()
        raise


def _ask_yn(prompt: str, default: bool = True) -> bool:
    """Ask a yes/no question. Returns bool."""
    hint = "[Y/n]" if default else "[y/N]"
    try:
        raw = input(f"{prompt} {hint}: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        raise
    if not raw:
        return default
    return raw in ("y", "yes", "1")


def _section(title: str) -> None:
    print()
    print(bold(cyan(f"{'─' * 44}")))
    print(bold(f"  {title}"))
    print(bold(cyan(f"{'─' * 44}")))
    print()


# The Key of Solomon was written so its invocations would outlast their author.
# chmod 600: owner-only. Some keys are not meant to be shared.
def _persist_env_file(lines: list[str]) -> None:
    """Write env vars to ~/.b1e55ed/env (systemd EnvironmentFile format).

    Also appends ``source ~/.b1e55ed/env`` to ~/.bashrc when missing so
    interactive shells pick up the variables too.
    """
    try:
        env_dir = b1e55ed_dir()
        env_dir.mkdir(parents=True, exist_ok=True)
        logs_dir().mkdir(parents=True, exist_ok=True)

        env_file = env_dir / "env"
        env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        env_file.chmod(0o600)

        # Append source line to ~/.bashrc so interactive shells pick it up
        bashrc = Path.home() / ".bashrc"
        source_line = "source ~/.b1e55ed/env"
        if bashrc.exists():
            content = bashrc.read_text(encoding="utf-8")
            if source_line not in content:
                with bashrc.open("a", encoding="utf-8") as f:
                    f.write(f"\n# b1e55ed environment\n{source_line}\n")

        print(f"  {_ok(f'Persisted to {env_file}:')}")
        for line in lines:
            if "MASTER_PASSWORD" in line:
                key, _ = line.split("=", 1)
                print(f"    {dim(f'{key}=***')}")
            else:
                print(f"    {dim(line)}")
        print(f"  {dim('File permissions: 600 (owner-only)')}")
    except Exception as e:  # noqa: BLE001
        print(f"  {yellow('⚠')} Could not persist env file: {e}")


# ── Symbol packs ─────────────────────────────────────────────────────────────

_SYMBOL_PACKS: dict[str, dict] = {
    "1": {
        "name": "Top 10 — Large caps (BTC, ETH, SOL, BNB, XRP, ADA, AVAX, DOT, LINK, UNI)",
        "symbols": ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "DOT", "LINK", "UNI"],
    },
    "2": {
        "name": "Top 30 — Broad coverage",
        "symbols": [
            "BTC",
            "ETH",
            "SOL",
            "BNB",
            "XRP",
            "ADA",
            "AVAX",
            "DOT",
            "LINK",
            "UNI",
            "LTC",
            "ATOM",
            "NEAR",
            "ARB",
            "OP",
            "MATIC",
            "FIL",
            "AAVE",
            "CRV",
            "SNX",
            "SUI",
            "APT",
            "INJ",
            "TIA",
            "SEI",
            "JTO",
            "WIF",
            "BONK",
            "JUP",
            "PYTH",
        ],
    },
    "3": {
        "name": "Top 50 — Comprehensive",
        "symbols": [
            "BTC",
            "ETH",
            "SOL",
            "BNB",
            "XRP",
            "ADA",
            "AVAX",
            "DOT",
            "LINK",
            "UNI",
            "LTC",
            "ATOM",
            "NEAR",
            "ARB",
            "OP",
            "MATIC",
            "FIL",
            "AAVE",
            "CRV",
            "SNX",
            "SUI",
            "APT",
            "INJ",
            "TIA",
            "SEI",
            "JTO",
            "WIF",
            "BONK",
            "JUP",
            "PYTH",
            "PEPE",
            "FLOKI",
            "MEME",
            "RENDER",
            "FET",
            "OCEAN",
            "AGIX",
            "TAO",
            "IO",
            "HYPE",
            "VIRTUAL",
            "AI16Z",
            "AIXBT",
            "GOAT",
            "DEGEN",
            "BRETT",
            "TOSHI",
            "MOG",
            "TURBO",
            "WEN",
        ],
    },
    "4": {
        "name": "Highest TVL — DeFi protocols",
        "symbols": [
            "ETH",
            "BTC",
            "SOL",
            "BNB",
            "AVAX",
            "MATIC",
            "ARB",
            "OP",
            "AAVE",
            "UNI",
            "CRV",
            "MKR",
            "COMP",
            "LDO",
            "RPL",
            "SUSHI",
            "BAL",
            "FXS",
            "CVX",
            "FRAX",
        ],
    },
    "5": {
        "name": "AI + Agent coins",
        "symbols": [
            "FET",
            "OCEAN",
            "AGIX",
            "RENDER",
            "TAO",
            "IO",
            "VIRTUAL",
            "AI16Z",
            "AIXBT",
            "GOAT",
            "GRASS",
            "PRIME",
            "ATH",
            "NOS",
        ],
    },
    "6": {
        "name": "Custom — enter your own",
        "symbols": [],
    },
}

# ── Step helpers ──────────────────────────────────────────────────────────────


def _step0_welcome() -> None:
    """Print the welcome banner."""
    from importlib.metadata import version as _pkg_version

    try:
        _ver = _pkg_version("b1e55ed")
    except Exception:  # noqa: BLE001
        _ver = "?"
    subtitle = f"contributor intelligence engine v{_ver}".center(40)
    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║" + bold("         b1e55ed setup wizard           ") + "║")
    print("  ║" + dim(subtitle) + "║")
    print("  ╚══════════════════════════════════════════╝")
    print()
    print("  This wizard will configure b1e55ed in 5 steps.")
    print("  Press " + bold("Ctrl+C") + " to exit at any time.")
    print()


def _step1_environment(repo_root: Path) -> bool:
    """Auto-check environment. Returns True if all checks pass."""
    _section("[1/5] Environment check")

    all_ok = True

    # Python version
    v = sys.version_info
    if v.major > 3 or (v.major == 3 and v.minor >= 11):
        print(f"  {_ok(f'Python {v.major}.{v.minor}.{v.micro}')}")
    else:
        print(f"  {_fail(f'Python {v.major}.{v.minor}.{v.micro} — need 3.11+')}")
        all_ok = False

    # SQLite
    try:
        sqlite3.connect(":memory:").execute("SELECT 1")
        print(f"  {_ok('SQLite available')}")
    except Exception as e:  # noqa: BLE001
        print(f"  {_fail(f'SQLite unavailable: {e}')}")
        all_ok = False

    # data/ directory
    data_dir = repo_root / "data"
    if data_dir.exists():
        print(f"  {_ok(f'data/ exists ({data_dir})')}")
    else:
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            print(f"  {_ok(f'data/ created ({data_dir})')}")
        except Exception as e:  # noqa: BLE001
            print(f"  {_fail(f'Could not create data/: {e}')}")
            all_ok = False

    # config/ directory
    config_dir = repo_root / "config"
    if config_dir.exists():
        print(f"  {_ok(f'config/ exists ({config_dir})')}")
    else:
        print(f"  {yellow('⚠')} config/ not found at {config_dir}")

    # Create ~/.b1e55ed/ directories
    try:
        _bd = b1e55ed_dir()
        _bd.mkdir(parents=True, exist_ok=True)
        logs_dir().mkdir(parents=True, exist_ok=True)
        print(f"  {_ok('~/.b1e55ed/ directory ready')}")
    except Exception as e:  # noqa: BLE001
        print(f"  {yellow('⚠')} Could not create ~/.b1e55ed/: {e}")

    print()
    if all_ok:
        print(f"  {green(bold('[1/5] Environment OK'))}")
    else:
        print(f"  {yellow('[1/5] Environment has issues — continuing anyway')}")
    return all_ok


def _step2_password() -> None:
    """Password setup step.

    Persists either B1E55ED_MASTER_PASSWORD or B1E55ED_DEV_MODE=1 to
    ``~/.b1e55ed/env`` so that both interactive shells (via ``source``)
    and systemd (via ``EnvironmentFile``) pick up the value.
    """
    _section("[2/5] Master password")
    print("  Your identity and keys are encrypted at rest with a master password.")
    print("  Set " + bold("B1E55ED_MASTER_PASSWORD") + " in your shell profile, or enter it each time.")
    print()

    env_lines: list[str] = []

    existing = os.environ.get("B1E55ED_MASTER_PASSWORD", "")
    if existing:
        print(f"  {_ok('B1E55ED_MASTER_PASSWORD already set in environment')}")
        env_lines.append(f"B1E55ED_MASTER_PASSWORD={existing}")
    else:
        try:
            import getpass

            password = getpass.getpass("  Enter master password (or press Enter to skip encryption): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            print(f"  {dim('Skipping password setup — setting DEV_MODE.')}")
            env_lines.append("B1E55ED_DEV_MODE=1")
            os.environ["B1E55ED_DEV_MODE"] = "1"
            password = ""

        if password:
            try:
                import getpass

                confirm = getpass.getpass("  Confirm password: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                print(f"  {dim('Skipping password setup — setting DEV_MODE.')}")
                env_lines.append("B1E55ED_DEV_MODE=1")
                os.environ["B1E55ED_DEV_MODE"] = "1"
                confirm = ""
                password = ""

            if password and password != confirm:
                print(f"  {red('Passwords do not match — setting DEV_MODE instead.')}")
                env_lines.append("B1E55ED_DEV_MODE=1")
                os.environ["B1E55ED_DEV_MODE"] = "1"
            elif password:
                print(f"  {_ok('Passwords match')}")
                env_lines.append(f"B1E55ED_MASTER_PASSWORD={password}")
                os.environ["B1E55ED_MASTER_PASSWORD"] = password
        elif not env_lines:
            print(f"  {dim('Skipping encryption — setting DEV_MODE.')}")
            env_lines.append("B1E55ED_DEV_MODE=1")
            os.environ["B1E55ED_DEV_MODE"] = "1"

    # Prompt for optional data API keys
    print()
    print("  " + bold("Data API keys") + " (optional — needed for on-chain and financial producers):")
    print()

    nansen_key = os.environ.get("B1E55ED_NANSEN_API_KEY", "") or os.environ.get("NANSEN_API_KEY", "")
    if nansen_key:
        print(f"  {_ok('Nansen API key found in environment')}")
        env_lines.append(f"NANSEN_API_KEY={nansen_key}")
    else:
        print(f"  {dim('Nansen — https://app.nansen.ai/settings/api — Read-only access')}")
        print(f"  {dim('Used by: on-chain smart money producers. Skippable (on-chain signals disabled).')}")
        try:
            nansen_key = _ask("  Nansen API key [Enter to skip]", default="")
        except (EOFError, KeyboardInterrupt):
            print()
            nansen_key = ""
        if nansen_key:
            env_lines.append(f"NANSEN_API_KEY={nansen_key}")
            print(f"  {_ok('Nansen key configured')}")
        else:
            print(f"  {dim('Skipping — add later via ~/.b1e55ed/env')}")

    fd_key = os.environ.get("B1E55ED_FD_API_KEY", "") or os.environ.get("FINANCIAL_DATASETS_API_KEY", "")
    if fd_key:
        print(f"  {_ok('Financial Datasets API key found in environment')}")
        env_lines.append(f"FINANCIAL_DATASETS_API_KEY={fd_key}")
    else:
        print(f"  {dim('Financial Datasets — https://financialdatasets.ai/settings — Read-only access')}")
        print(f"  {dim('Used by: TradFi producers (earnings, SEC filings). Skippable (TradFi signals disabled).')}")
        try:
            fd_key = _ask("  Financial Datasets API key [Enter to skip]", default="")
        except (EOFError, KeyboardInterrupt):
            print()
            fd_key = ""
        if fd_key:
            env_lines.append(f"FINANCIAL_DATASETS_API_KEY={fd_key}")
            print(f"  {_ok('Financial Datasets key configured')}")
        else:
            print(f"  {dim('Skipping — add later via ~/.b1e55ed/env')}")

    _persist_env_file(env_lines)


def _check_rust_grinder() -> str | None:
    """Return path to Rust forge binary if available, else None."""
    import shutil

    candidates = [
        Path.home() / ".local" / "share" / "b1e55ed" / "bin" / "b1e55ed-forge",
        Path.home() / ".local" / "bin" / "b1e55ed-forge",
    ]
    for p in candidates:
        if p.exists() and os.access(str(p), os.X_OK):
            return str(p)
    found = shutil.which("b1e55ed-forge")
    return found


def _auto_download_forge() -> str | None:
    """Download the Rust forge binary for the current platform. Returns install path or None."""
    import platform
    import stat
    import urllib.request

    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "darwin":
        artifact = "b1e55ed-forge-macos"  # universal binary (arm64 + x86_64)
    elif system == "linux" and machine == "x86_64":
        artifact = "b1e55ed-forge-linux-x86_64"
    else:
        print(f"  {yellow('⚠')} No pre-built binary for {system}/{machine}.")
        return None

    # /releases/latest skips pre-releases — resolve tag via API instead
    try:
        with urllib.request.urlopen(  # noqa: S310
            "https://api.github.com/repos/P-U-C/b1e55ed/releases?per_page=1"
        ) as resp:
            import json as _json

            releases = _json.loads(resp.read())
            tag = releases[0]["tag_name"] if releases else None
    except Exception:  # noqa: BLE001
        tag = None

    if not tag:
        print(f"  {red('✗')} Could not resolve latest release tag.")
        return None

    url = f"https://github.com/P-U-C/b1e55ed/releases/download/{tag}/{artifact}"
    dest_dir = Path.home() / ".local" / "share" / "b1e55ed" / "bin"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "b1e55ed-forge"

    print(f"  Downloading {artifact}...")
    try:
        urllib.request.urlretrieve(url, dest)  # noqa: S310
        dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        # macOS: clear quarantine bit so Gatekeeper doesn't silently kill the binary
        import platform as _platform

        if _platform.system() == "Darwin":
            subprocess.run(
                ["xattr", "-dr", "com.apple.quarantine", str(dest)],
                check=False,
                capture_output=True,
            )
        print(f"  {_ok(f'Forge binary installed: {dest}')}")
        return str(dest)
    except Exception as e:  # noqa: BLE001
        print(f"  {red('✗')} Download failed: {e}")
        return None


# Identity is not configured. It becomes through action.
# Beauvoir: one is not born, but rather becomes.
def _step3_identity(repo_root: Path) -> None:
    """Identity forge/restore step."""
    _section("[3/5] Identity")

    identity_path = repo_root / ".b1e55ed" / "identity.json"

    if identity_path.exists():
        try:
            import json

            data = json.loads(identity_path.read_text(encoding="utf-8"))
            address = data.get("address", "???")
            node_id = data.get("node_id", "???")
            print(f"  {_ok(f'Identity found: {address} ({node_id})')}")
            print(f"  {dim('Re-running wizard will not re-forge your identity.')}")
            return
        except Exception:  # noqa: BLE001
            print(f"  {yellow('⚠')} Existing identity file could not be read — will offer to forge.")

    print("  Your identity is an Ethereum address with a " + bold("0xb1e55ed") + " prefix.")
    print()

    rust_binary = _check_rust_grinder()

    if rust_binary:
        # Fast path: Rust binary available
        print(f"  {_ok(f'Rust grinder found: {rust_binary}')}")
        print("  Forging a vanity address takes seconds to ~2 min depending on hardware.")
        print()

        try:
            forge = _ask_yn("  Forge vanity identity (0xb1e55ed prefix)?", default=True)
        except (EOFError, KeyboardInterrupt):
            print()
            print(f"  {dim('Skipping identity forge.')}")
            return

        if forge:
            print()
            print(f"  {dim('Running: b1e55ed identity forge')}")
            print()
            try:
                import shutil as _shutil

                _b1e55ed = _shutil.which("b1e55ed")
                _forge_cmd: list[str] = [_b1e55ed, "identity", "forge"] if _b1e55ed is not None else [sys.executable, "-m", "engine.cli", "identity", "forge"]

                proc = subprocess.run(
                    _forge_cmd,
                    cwd=str(repo_root),
                    check=False,
                )
                if proc.returncode == 0:
                    print(f"\n  {_ok('Identity forged successfully')}")
                else:
                    print(f"\n  {yellow('⚠')} Identity forge exited with code {proc.returncode}")
                    print(f"  {dim('You can retry later: b1e55ed identity forge')}")
            except Exception as e:  # noqa: BLE001
                print(f"\n  {red('⚠')} Could not run forge: {e}")
                print(f"  {dim('Try manually: b1e55ed identity forge')}")
        else:
            print()
            print(f"  {dim('To restore an existing identity:')}")
            print("    b1e55ed identity restore --eth-key <your-private-key-hex>")
    else:
        # No Rust binary found — auto-download it
        print(f"  {yellow('⚠')} Rust forge binary not found — downloading now...")
        print()
        rust_binary = _auto_download_forge()
        if rust_binary:
            print()
            print(f"  {dim('Running: b1e55ed identity forge')}")
            print()
            try:
                import shutil as _shutil

                _b1e55ed = _shutil.which("b1e55ed")
                _forge_cmd = [_b1e55ed, "identity", "forge"] if _b1e55ed is not None else [sys.executable, "-m", "engine.cli", "identity", "forge"]

                proc = subprocess.run(
                    _forge_cmd,
                    cwd=str(repo_root),
                    check=False,
                )
                if proc.returncode == 0:
                    print(f"\n  {_ok('Identity forged successfully')}")
                else:
                    print(f"\n  {yellow('⚠')} Identity forge exited with code {proc.returncode}")
                    print(f"  {dim('You can retry: b1e55ed identity forge')}")
            except Exception as e:  # noqa: BLE001
                print(f"\n  {red('⚠')} Could not run forge: {e}")
        else:
            print()
            print(f"  {dim('Run `b1e55ed identity forge` after installing the binary manually.')}")


def _step4_configuration(repo_root: Path) -> None:
    """Configuration step."""
    _section("[4/5] Configuration")

    user_cfg = repo_root / "config" / "user.yaml"

    if user_cfg.exists():
        print(f"  {_ok(f'config/user.yaml already exists ({user_cfg})')}")
        print()
        # Show a brief summary
        try:
            content = user_cfg.read_text(encoding="utf-8")
            print(f"  {dim('Current config preview:')}")
            for line in content.splitlines()[:15]:
                print(f"  {dim(line)}")
            if len(content.splitlines()) > 15:
                print(f"  {dim('...')}")
            print()
        except Exception:  # noqa: BLE001
            pass

        try:
            modify = _ask_yn("  Modify configuration?", default=False)
        except (EOFError, KeyboardInterrupt):
            print()
            print(f"  {dim('Keeping existing configuration.')}")
            return

        if not modify:
            print(f"  {dim('Keeping existing configuration.')}")
            return

    print()
    print("  " + bold("API auth token") + " (protects your local API endpoint):")
    try:
        api_token = _ask("  Token", default="auto-generate")
    except (EOFError, KeyboardInterrupt):
        print()
        api_token = "auto-generate"

    if api_token == "auto-generate" or not api_token:
        api_token = secrets.token_urlsafe(32)
        print(f"  {_ok(f'Generated token: {api_token[:16]}...')}")

    print()
    print("  " + bold("Brain cycle symbols") + " — choose a pack:")
    print()
    for key, pack in _SYMBOL_PACKS.items():
        print(f"  {bold(key)}) {pack['name']}")
    print()
    try:
        pack_choice = _ask("  Pack", default="1")
    except (EOFError, KeyboardInterrupt):
        print()
        pack_choice = "1"

    if pack_choice not in _SYMBOL_PACKS:
        pack_choice = "1"

    if pack_choice == "6":
        try:
            symbols_raw = _ask("  Symbols (comma-separated)", default="BTC,ETH,SOL")
        except (EOFError, KeyboardInterrupt):
            symbols_raw = "BTC,ETH,SOL"
        symbols = [s.strip().upper() for s in symbols_raw.split(",") if s.strip()] or ["BTC", "ETH", "SOL"]
    else:
        symbols = _SYMBOL_PACKS[pack_choice]["symbols"]
        print(f"  {_ok(f'Pack selected: {len(symbols)} symbols')}")

    # Determine if GitHub App auth is pre-configured (baked-in app_id)
    try:
        from engine.config.github_app_defaults import (
            COMMUNITY_APP_ID,
            COMMUNITY_INSTALLATION_ID,
        )

        app_auth_baked_in = COMMUNITY_APP_ID != 0 and COMMUNITY_INSTALLATION_ID != 0
        baked_app_id = COMMUNITY_APP_ID
        baked_installation_id = COMMUNITY_INSTALLATION_ID
    except Exception:  # noqa: BLE001
        app_auth_baked_in = False
        baked_app_id = 0
        baked_installation_id = 0

    github_token = ""

    if app_auth_baked_in:
        # GitHub App handles auth automatically — no PAT needed
        print()
        print(f"  {_ok('GitHub App auth is pre-configured (app_id=' + str(baked_app_id) + ')')}")
        print(f"  {dim('No GitHub token needed — the community app handles auth automatically.')}")
        print(f"  {dim('Set B1E55ED_GITHUB_APP_KEY env var to your app private key PEM to enable publishing.')}")
    else:
        print()
        print("  " + bold("GitHub publish token") + " — required to track your contributions publicly.")
        print()
        print(f"  {dim('Contributions without a token are scored locally only (not publicly visible).')}")
        print(f"  {dim('Create a fine-grained PAT at: https://github.com/settings/tokens?type=beta')}")
        print(f"  {dim('Required permissions: Issues → Read & Write on P-U-C/b1e55ed only.')}")
        print()
        print(f"  {dim('Alternative: configure GitHub App auth (see publish.github.app_id in config).')}")
        print()

        # Check environment first
        env_token = os.environ.get("B1E55ED_GITHUB_TOKEN", "") or os.environ.get("GITHUB_TOKEN", "")
        if env_token:
            print(f"  {_ok('Token found in environment (B1E55ED_GITHUB_TOKEN / GITHUB_TOKEN)')}")
            github_token = env_token
        else:
            try:
                github_token = _ask("  GitHub token (or press Enter to skip — you can add later)", default="")
            except (EOFError, KeyboardInterrupt):
                print()
                github_token = ""

            if not github_token:
                print()
                print(f"  {yellow('⚠')} No token set — contributions will be scored locally only.")
                print(f"  {dim('Add later: set B1E55ED_GITHUB_TOKEN=<token> and re-run wizard.')}")
            else:
                print(f"  {_ok('Token configured')}")

    # Build config YAML
    symbols_yaml = "[" + ", ".join(f'"{s}"' for s in symbols) + "]"
    github_token_value = github_token if github_token else ""

    if app_auth_baked_in:
        github_publish_block = f"""publish:
  github:
    # GitHub App auth (preferred — no token needed when app_id is set)
    app_id: {baked_app_id}        # community GitHub App (pre-configured)
    installation_id: {baked_installation_id}
    # Set B1E55ED_GITHUB_APP_KEY env var to your app's private key PEM
    token: ""        # fallback PAT (used if app_id is 0)
    owner: "P-U-C"
    repo: "offchain-attestations"
    labels: ["b1e55ed-attestation"]
"""
    else:
        github_publish_block = f"""publish:
  github:
    # GitHub App auth (preferred — no token needed when app_id is set)
    app_id: 0        # set to enable GitHub App auth
    installation_id: 0
    # Set B1E55ED_GITHUB_APP_KEY env var to your app's private key PEM
    token: "{github_token_value}"        # fallback PAT (used if app_id is 0)
    owner: "P-U-C"
    repo: "offchain-attestations"
    labels: ["b1e55ed-attestation"]
"""

    # Daemon interval configuration
    print()
    print("  " + bold("Daemon intervals") + " — how often each subsystem runs:")
    print()
    print(f"  {dim('Press Enter to accept defaults (recommended).')}")
    print()

    try:
        brain_interval = _ask("  Brain fast cycle (seconds)", default="300")
        brain_interval = int(brain_interval) if brain_interval.isdigit() else 300
    except (EOFError, KeyboardInterrupt, ValueError):
        brain_interval = 300

    try:
        brain_full_interval = _ask("  Brain full cycle (seconds)", default="21600")
        brain_full_interval = int(brain_full_interval) if brain_full_interval.isdigit() else 21600
    except (EOFError, KeyboardInterrupt, ValueError):
        brain_full_interval = 21600

    try:
        resolver_interval = _ask("  Outcome resolver (seconds)", default="1800")
        resolver_interval = int(resolver_interval) if resolver_interval.isdigit() else 1800
    except (EOFError, KeyboardInterrupt, ValueError):
        resolver_interval = 1800

    print(f"  {_ok(f'brain={brain_interval}s, brain-full={brain_full_interval}s, resolver={resolver_interval}s')}")

    config_content = f"""# Generated by `b1e55ed wizard`
preset: balanced

brain:
  cycle_interval_seconds: 1800

universe:
  symbols: {symbols_yaml}
  max_size: 100

execution:
  mode: paper
  paper_start_balance: 10000.0
  confirmation_threshold_usd: 500.0
  paper_min_days: 14

api:
  host: "127.0.0.1"
  port: 5050
  auth_token: "{api_token}"
  cors_origins: []

dashboard:
  host: "127.0.0.1"
  port: 5051
  auth_token: ""

daemon:
  brain_interval_seconds: {brain_interval}
  brain_full_interval_seconds: {brain_full_interval}
  resolver_interval_seconds: {resolver_interval}

{github_publish_block}"""

    try:
        user_cfg.parent.mkdir(parents=True, exist_ok=True)
        user_cfg.write_text(config_content, encoding="utf-8")
        print()
        print(f"  {_ok(f'config/user.yaml written ({user_cfg})')}")
    except Exception as e:  # noqa: BLE001
        print()
        print(f"  {red('⚠')} Could not write config: {e}")
        print(f"  {dim('Create config/user.yaml manually.')}")


_ORACLE_URL = "https://oracle.b1e55ed.permanentupperclass.com"


# RFC 7231 §6.5.9 defines 409 as "conflict with the current state of the target resource."
# Translation: you are already here.  The ledger does not need a second entry.
def _step_register_contributor(repo_root: Path) -> None:
    """Auto-register new contributor via the oracle (no credentials needed on user machine)."""
    import json as _json
    import urllib.error
    import urllib.request

    _section("[4b] Contributor registration")

    identity_path = repo_root / ".b1e55ed" / "identity.json"
    if not identity_path.exists():
        print(f"  {dim('No identity — skipping registration.')}")
        return

    try:
        data = _json.loads(identity_path.read_text(encoding="utf-8"))
        node_id = data.get("node_id", "")
        address = data.get("address", "")
    except Exception:  # noqa: BLE001
        print(f"  {yellow('⚠')} Could not read identity — skipping.")
        return

    if not node_id:
        return

    # Dwork & Naor, 1992: proof of work prevents repeated submissions.
    # A simpler proof: the file that says you already submitted.
    # Fast path: contributor_id already written into identity.json means we registered before.
    # This survives DB wipes and oracle restarts — the ledger entry is permanent.
    if data.get("contributor_id"):
        print(f"  {_ok('Already registered (skipping)')}")
        return

    print(f"  Registering: {dim(node_id)}")
    print()

    # Try oracle first — it holds the GitHub App key, creates the issue server-side
    # Oracle is the source of truth: 409 = already registered, no side-effect needed.
    issue_url: str | None = None
    registered = False
    already_registered = False
    oracle_err: Exception | None = None
    local_err: Exception | None = None

    try:
        payload = _json.dumps({"node_id": node_id, "name": address or node_id, "role": "contributor"}).encode()
        req = urllib.request.Request(
            f"{_ORACLE_URL}/api/v1/oracle/contributors/register",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            result = _json.loads(resp.read())
            issue_url = result.get("issue_url")
            registered = True
            # Persist contributor_id into identity.json so future wizard runs skip this step
            try:
                _id_data = _json.loads(identity_path.read_text(encoding="utf-8"))
                _id_data["contributor_id"] = result.get("contributor_id")
                identity_path.write_text(_json.dumps(_id_data, indent=2), encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass  # non-fatal — worst case wizard re-runs step next time
    except urllib.error.HTTPError as e:
        if e.code == 409:
            already_registered = True  # oracle confirms: already registered
            registered = True
        else:
            oracle_err = e
    except Exception as e:  # noqa: BLE001
        oracle_err = e  # oracle unreachable — fall through to local

    # Short-circuit: oracle confirmed already registered — nothing more to do
    # The oracle does not forget. Neither does the chain.
    if already_registered:
        print(f"  {_ok('Already registered (skipping)')}")
        return

    # Register locally too (idempotent)
    try:
        from engine.core.contributors import ContributorRegistry as _Registry
        from engine.core.database import Database as _Database

        _db_path = repo_root / "data" / "brain.db"
        _db_path.parent.mkdir(parents=True, exist_ok=True)
        _reg = _Registry(_Database(str(_db_path)))
        _reg.register(
            node_id=node_id,
            name=address or node_id,
            role="contributor",
        )
        registered = True
    except ValueError:
        registered = True  # already registered locally — idempotent
    except Exception as e:  # noqa: BLE001
        local_err = e  # local DB unavailable — oracle registration is enough

    if registered:
        print(f"  {_ok('Registered as contributor')}")
        if issue_url:
            print(f"  {_ok(f'Announced: {issue_url}')}")
    else:
        print(f"  {yellow('⚠')} Registration failed — run manually: b1e55ed contributors register")
        if oracle_err is not None:
            print(f"  {dim('Oracle error:')} {oracle_err!r}")
        if local_err is not None:
            print(f"  {dim('Local error:')}  {local_err!r}")


def _step_systemd(repo_root: Path) -> None:  # noqa: ARG001
    """Offer to install b1e55ed as a systemd service (Linux only)."""
    import platform
    import shutil

    # Only Linux — skip silently on macOS/Windows
    if platform.system() != "Linux":
        return

    _section("[4c] System service")

    # Check prerequisites
    if not shutil.which("systemctl"):
        print(f"  {yellow('⚠')} systemctl not found — skipping systemd setup.")
        return
    if not shutil.which("sudo"):
        print(f"  {yellow('⚠')} sudo not found — skipping systemd setup.")
        return

    service_path = Path("/etc/systemd/system/b1e55ed.service")
    if service_path.exists():
        print(f"  {_ok('Already installed (skipping)')}")
        return

    try:
        install = _ask_yn("  Install b1e55ed as a systemd service (auto-start on boot)?", default=False)
    except (EOFError, KeyboardInterrupt):
        print()
        print(f"  {dim('Skipping systemd setup.')}")
        return

    if not install:
        print(f"  {dim('Skipping.')}")
        return

    import getpass

    _current_user = getpass.getuser()
    _home = str(Path.home())

    unit_content = f"""\
[Unit]
Description=b1e55ed trading intelligence
After=network.target

[Service]
Type=simple
User={_current_user}
WorkingDirectory={_home}
EnvironmentFile=-{_home}/.b1e55ed/env
ExecStart={_home}/.local/bin/b1e55ed daemon
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""

    try:
        subprocess.run(
            ["sudo", "tee", "/etc/systemd/system/b1e55ed.service"],
            input=unit_content.encode(),
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"  {_fail('Could not write service file')}")
        stderr = e.stderr.decode().strip() if e.stderr else ""
        if stderr:
            print(f"  {dim(f'Error: {stderr}')}")
        return
    except Exception as e:  # noqa: BLE001
        print(f"  {_fail(f'Could not write service file: {e}')}")
        return

    try:
        subprocess.run(
            ["sudo", "systemctl", "daemon-reload"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["sudo", "systemctl", "enable", "b1e55ed"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["sudo", "systemctl", "start", "b1e55ed"],
            check=True,
            capture_output=True,
        )
        print(f"  {_ok('systemd service installed, enabled, and started')}")
        print(f"  {dim('Manage with: sudo systemctl [status|stop|restart] b1e55ed')}")
    except subprocess.CalledProcessError as e:
        print(f"  {yellow('⚠')} Service installed but could not start automatically.")
        print(f"  {dim('Try: sudo systemctl start b1e55ed')}")
        stderr = e.stderr.decode().strip() if e.stderr else ""
        if stderr:
            print(f"  {dim(f'Error: {stderr}')}")


def _step_brain_cron(repo_root: Path) -> None:  # noqa: ARG001
    """Legacy brain cron step — superseded by ``b1e55ed daemon``.

    If an old brain cron exists, offer to remove it since the unified
    daemon supervisor now handles brain scheduling.
    """
    # Check if a legacy brain cron exists and offer to clean it up
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            check=False,
        )
        if "b1e55ed brain" in (result.stdout or ""):
            print()
            print(f"  {yellow('⚠')} Legacy brain cron detected.")
            print(f"  {dim('The daemon supervisor now handles brain scheduling — cron is no longer needed.')}")
            try:
                remove = _ask_yn("  Remove legacy brain cron entry?", default=True)
            except (EOFError, KeyboardInterrupt):
                print()
                return

            if remove:
                # Filter out the b1e55ed brain line
                lines = [line for line in (result.stdout or "").splitlines() if "b1e55ed brain" not in line]
                new_crontab = "\n".join(lines) + "\n" if lines else ""
                subprocess.run(
                    ["bash", "-c", f'echo "{new_crontab}" | crontab -'],
                    check=True,
                    capture_output=True,
                )
                print(f"  {_ok('Legacy brain cron removed')}")
    except Exception:  # noqa: BLE001
        pass  # No crontab available — nothing to clean up


def _step5_test_run(repo_root: Path) -> None:
    """Optional first-run brain test."""
    _section("[5/5] Test run")
    print("  Run a quick health check to verify your setup?")
    print(f"  {dim('(Runs: b1e55ed health)')}")
    print()

    try:
        run_test = _ask_yn("  Run test?", default=True)
    except (EOFError, KeyboardInterrupt):
        print()
        print(f"  {dim('Skipping test run.')}")
        return

    if not run_test:
        print(f"  {dim('Skipping. Run manually: b1e55ed brain')}")
        return

    print()
    print(f"  {dim('Running health check...')}")
    print()

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "engine.cli", "health"],
            cwd=str(repo_root),
            check=False,
            timeout=30,
        )
        if proc.returncode == 0:
            print(f"  {_ok('Health check passed')}")
        else:
            print(f"  {yellow('⚠')} Health check returned code {proc.returncode}")
            print(f"  {dim('Run manually: b1e55ed health')}")
    except subprocess.TimeoutExpired:
        print(f"  {yellow('⚠')} Health check timed out")
    except Exception as e:  # noqa: BLE001
        print(f"  {yellow('⚠')} Could not run health check: {e}")


def _completion() -> None:
    """Print the completion summary."""
    print()
    print("  " + green("══════════════════════════════════════"))
    print("  " + bold(green("  Setup complete. ✓")))
    print()
    print(f"  {bold('Start everything:')}    b1e55ed daemon")
    print(f"  {bold('Check daemon status:')} b1e55ed daemon --status")
    print(f"  {bold('Run brain once:')}      b1e55ed brain")
    print(f'  {bold("Submit a signal:")}     b1e55ed signal "BTC looking strong" --direction bullish')
    print(f"  {bold('Check your status:')}   b1e55ed contributors score --id <your-id>")
    print()
    print(f"  {bold('Docs:')} https://github.com/P-U-C/b1e55ed/tree/main/docs")
    print("  " + green("══════════════════════════════════════"))
    print()


# ── Public entrypoint ─────────────────────────────────────────────────────────


# A wizard that repeats steps the initiate has already passed is not wise — it is forgetful.
def run_wizard(ctx: CliContext, args: argparse.Namespace) -> int:  # noqa: ARG001
    """Run the interactive b1e55ed setup wizard."""
    repo_root = ctx.repo_root

    try:
        _step0_welcome()
    except (EOFError, KeyboardInterrupt):
        print("\n  Wizard interrupted.")
        return 1

    steps = [
        lambda: _step1_environment(repo_root),
        lambda: _step2_password(),
        lambda: _step3_identity(repo_root),
        lambda: _step4_configuration(repo_root),
        lambda: _step_register_contributor(repo_root),
        lambda: _step_systemd(repo_root),
        lambda: _step_brain_cron(repo_root),
        lambda: _step5_test_run(repo_root),
    ]

    for step_fn in steps:
        try:
            step_fn()  # type: ignore[no-untyped-call]
        except KeyboardInterrupt:
            print()
            print(f"\n  {yellow('Wizard interrupted. Run `b1e55ed wizard` to continue.')}")
            return 1
        except Exception as e:  # noqa: BLE001
            # Never crash — just warn and continue to next step
            print(f"\n  {yellow('⚠')} Step error (continuing): {e}")

    import contextlib

    with contextlib.suppress(Exception):
        _completion()

    return 0
