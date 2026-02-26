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
    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║" + bold("         b1e55ed setup wizard           ") + "║")
    print("  ║" + dim("  contributor intelligence engine v1.x  ") + "║")
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

    print()
    if all_ok:
        print(f"  {green(bold('[1/5] Environment OK'))}")
    else:
        print(f"  {yellow('[1/5] Environment has issues — continuing anyway')}")
    return all_ok


def _step2_password() -> None:
    """Password setup step."""
    _section("[2/5] Master password")
    print("  Your identity and keys are encrypted at rest with a master password.")
    print("  Set " + bold("B1E55ED_MASTER_PASSWORD") + " in your shell profile, or enter it each time.")
    print()

    existing = os.environ.get("B1E55ED_MASTER_PASSWORD", "")
    if existing:
        print(f"  {_ok('B1E55ED_MASTER_PASSWORD already set in environment')}")
        return

    try:
        import getpass

        password = getpass.getpass("  Enter master password (or press Enter to skip encryption): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        print(f"  {dim('Skipping password setup.')}")
        return

    if not password:
        print(f"  {dim('Skipping encryption.')}")
        return

    try:
        import getpass

        confirm = getpass.getpass("  Confirm password: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        print(f"  {dim('Skipping password setup.')}")
        return

    if password != confirm:
        print(f"  {red('Passwords do not match — skipping.')}")
        return

    print(f"  {_ok('Passwords match')}")

    try:
        save = _ask_yn("  Save B1E55ED_MASTER_PASSWORD to shell profile?", default=True)
    except (EOFError, KeyboardInterrupt):
        print()
        print(f"  {dim('Skipping shell profile update.')}")
        return

    if save:
        export_line = f'export B1E55ED_MASTER_PASSWORD="{password}"'
        saved_to: list[str] = []

        for rc in [Path.home() / ".bashrc", Path.home() / ".zshrc"]:
            if rc.exists():
                existing_content = rc.read_text(encoding="utf-8")
                if "B1E55ED_MASTER_PASSWORD" not in existing_content:
                    try:
                        with rc.open("a", encoding="utf-8") as f:
                            f.write(f"\n# b1e55ed master password\n{export_line}\n")
                        saved_to.append(str(rc))
                    except Exception as e:  # noqa: BLE001
                        print(f"  {yellow('⚠')} Could not write to {rc}: {e}")

        if saved_to:
            print(f"  {_ok('Saved to: ' + ', '.join(saved_to))}")
            print(f"  {dim('Reload your shell or run: source ~/.bashrc')}")
        else:
            print(f"  {yellow('⚠')} No shell rc files found to update. Set manually:")
            print(f"    {export_line}")
    else:
        print(f"  {dim('Password not saved — set B1E55ED_MASTER_PASSWORD manually when needed.')}")


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
            return
        except Exception:  # noqa: BLE001
            print(f"  {yellow('⚠')} Existing identity file could not be read — will offer to forge.")

    print("  Your identity is an Ethereum address with a " + bold("0xb1e55ed") + " prefix.")
    print("  Forging takes 10–60 seconds (proof-of-work vanity mining).")
    print()

    try:
        forge = _ask_yn("  Forge new identity?", default=True)
    except (EOFError, KeyboardInterrupt):
        print()
        print(f"  {dim('Skipping identity forge.')}")
        return

    if forge:
        print()
        print(f"  {dim('Running: b1e55ed identity forge')}")
        print()
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "engine.cli", "identity", "forge"],
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

    print()
    print("  " + bold("GitHub publish token") + " — required to track your contributions publicly.")
    print()
    print(f"  {dim('Contributions without a token are scored locally only (not publicly visible).')}")
    print(f"  {dim('Create a fine-grained PAT at: https://github.com/settings/tokens?type=beta')}")
    print(f"  {dim('Required permissions: Contents → Read & Write on P-U-C/b1e55ed only.')}")
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
    github_token_comment = "" if github_token else "  # set to enable public attestations"

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

publish:
  github:
    token: "{github_token_value}"{github_token_comment}
    owner: "P-U-C"
    repo: "b1e55ed"
    labels: ["b1e55ed-attestation"]
"""

    try:
        user_cfg.parent.mkdir(parents=True, exist_ok=True)
        user_cfg.write_text(config_content, encoding="utf-8")
        print()
        print(f"  {_ok(f'config/user.yaml written ({user_cfg})')}")
    except Exception as e:  # noqa: BLE001
        print()
        print(f"  {red('⚠')} Could not write config: {e}")
        print(f"  {dim('Create config/user.yaml manually.')}")


def _step5_test_run(repo_root: Path) -> None:
    """Optional first-run brain test."""
    _section("[5/5] Test run")
    print("  Run a quick brain cycle to verify your setup?")
    print(f"  {dim('(Runs: b1e55ed brain --symbols BTC --dry-run)')}")
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
    print(f"  {dim('Running brain cycle...')}")
    print()

    # Try --dry-run first; if unsupported, just skip
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "engine.cli", "brain", "--symbols", "BTC", "--dry-run"],
            cwd=str(repo_root),
            check=False,
            timeout=120,
        )
        if proc.returncode == 0:
            print(f"  {_ok('Test run completed successfully')}")
        else:
            # --dry-run not supported; try plain brain briefly
            proc2 = subprocess.run(
                [sys.executable, "-m", "engine.cli", "health"],
                cwd=str(repo_root),
                check=False,
                timeout=30,
            )
            if proc2.returncode == 0:
                print(f"  {_ok('Health check passed (brain test skipped — run manually)')}")
            else:
                print(f"  {yellow('⚠')} Test run exited with code {proc.returncode}")
                print(f"  {dim('Run manually: b1e55ed brain')}")
    except subprocess.TimeoutExpired:
        print(f"  {yellow('⚠')} Test run timed out (120s)")
        print(f"  {dim('Run manually: b1e55ed brain')}")
    except Exception as e:  # noqa: BLE001
        print(f"  {yellow('⚠')} Could not run test: {e}")
        print(f"  {dim('Run manually: b1e55ed brain')}")


def _completion() -> None:
    """Print the completion summary."""
    print()
    print("  " + green("══════════════════════════════════════"))
    print("  " + bold(green("  Setup complete. ✓")))
    print()
    print(f"  {bold('Start the brain:')}     b1e55ed brain")
    print(f'  {bold("Submit a signal:")}     b1e55ed signal "BTC looking strong" --direction bullish')
    print(f"  {bold('Check your status:')}   b1e55ed contributors score --id <your-id>")
    print(f"  {bold('Start the API:')}       b1e55ed api")
    print()
    print(f"  {bold('Docs:')} https://github.com/P-U-C/b1e55ed/tree/main/docs")
    print("  " + green("══════════════════════════════════════"))
    print()


# ── Public entrypoint ─────────────────────────────────────────────────────────


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
