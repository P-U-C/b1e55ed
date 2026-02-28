"""engine.cli.commands.setup — operator setup dispatcher."""

from __future__ import annotations

import argparse


def build_setup_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = sub.add_parser(
        "setup",
        help="Operator setup: standalone (CLI-only) or connected (OpenClaw + Telegram)",
    )
    p.add_argument(
        "mode",
        nargs="?",
        choices=["standalone", "connected"],
        help="Deployment mode: 'standalone' (self-contained CLI) or 'connected' (OpenClaw + Telegram orchestration).",
    )
    p.add_argument(
        "--non-interactive",
        action="store_true",
        help="Run without prompts (uses env vars).",
    )
    p.add_argument(
        "--preset",
        choices=["conservative", "balanced", "degen"],
        help="Config preset (standalone mode only).",
    )
    return p


def run_setup(ctx: object, args: argparse.Namespace) -> int:
    import subprocess
    import sys
    from pathlib import Path

    non_interactive = bool(getattr(args, "non_interactive", False))
    mode = getattr(args, "mode", None)

    if not mode:
        # Only prompt when interactive input is available.
        if non_interactive or not sys.stdin.isatty():
            mode = "standalone"
        else:
            print("\nb1e55ed operator setup\n")
            print("Choose your deployment mode:")
            print("  [1] standalone  — CLI + dashboard, self-contained")
            print("  [2] connected   — CLI + OpenClaw + Telegram orchestration")
            print()
            try:
                choice = input("Mode [1/2]: ").strip().lower()
            except (EOFError, OSError):
                choice = "1"
            mode = "standalone" if choice in ("1", "standalone", "") else "connected"

    if mode == "standalone":
        # Use Python implementation (works in CI and installed packages)
        from engine.cli.main import _cmd_setup

        return _cmd_setup(ctx, args)

    if mode == "connected":
        # Shell out to setup-connected.sh (interactive mode)
        scripts_dir = Path(__file__).parent.parent.parent.parent / "scripts"
        script = scripts_dir / "setup-connected.sh"
        if not script.exists():
            print(f"error: setup script not found: {script}", file=sys.stderr)
            return 2

        print("\n→ Running connected setup...\n")
        result = subprocess.run(["bash", str(script)], check=False)
        return int(result.returncode)

    print(f"error: unknown mode: {mode}", file=sys.stderr)
    return 2
