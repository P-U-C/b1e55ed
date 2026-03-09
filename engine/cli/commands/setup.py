"""engine.cli.commands.setup — operator setup dispatcher."""

from __future__ import annotations

import argparse


def build_setup_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = sub.add_parser(
        "setup",
        help="Operator setup: standalone (CLI-only) or connected (OpenClaw + Telegram) or repair",
    )
    p.add_argument(
        "mode",
        nargs="?",
        choices=["standalone", "connected", "repair"],
        help="Deployment mode: 'standalone' (self-contained CLI), 'connected' (OpenClaw + Telegram), or 'repair' (fix config issues).",
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


def _run_repair() -> int:
    """Repair operator config: fix /tmp path pollution, reset kill switch."""
    import sys

    print("\nb1e55ed setup repair\n")

    actions: list[str] = []

    # 1) Fix user.yaml /tmp path pollution
    try:
        from engine.cli.doctor import _repair_user_config

        result = _repair_user_config()
        if result:
            actions.append(result)
            print(f"  ✅ {result}")
        else:
            print("  ✅ user.yaml: no /tmp path pollution detected")
    except Exception as e:
        print(f"  ❌ Config repair failed: {e}", file=sys.stderr)

    # 2) Reset kill switch if stuck
    try:
        from engine.core.database import Database
        from engine.core.events import EventType
        from engine.core.paths import data_dir

        db_path = data_dir() / "brain.db"
        if db_path.exists():
            db = Database(db_path)
            try:
                row = db.conn.execute("SELECT payload FROM events WHERE type = 'KILL_SWITCH_V1' ORDER BY ts DESC LIMIT 1").fetchone()
                if row:
                    import json as _json

                    _ks_payload = _json.loads(row[0]) if isinstance(row[0], str) else row[0]
                    level = int(_ks_payload.get("level", 0))
                    if level > 0:
                        db.append_event(
                            event_type=EventType.KILL_SWITCH_V1,
                            payload={
                                "level": 0,
                                "previous_level": level,
                                "reason": "setup repair: reset to SAFE",
                                "auto": True,
                                "actor": "setup_repair",
                            },
                            source="cli.setup",
                        )
                        actions.append(f"Reset kill switch from level {level} to SAFE")
                        print(f"  ✅ Kill switch reset from level {level} to SAFE")
                    else:
                        print("  ✅ Kill switch: already SAFE (level 0)")
                else:
                    print("  ✅ Kill switch: SAFE (no events)")
            finally:
                db.close()
        else:
            print("  ✅ No database yet (nothing to repair)")
    except Exception as e:
        print(f"  ❌ Kill switch repair failed: {e}", file=sys.stderr)

    print()
    if actions:
        print(f"  Repaired {len(actions)} issue{'s' if len(actions) != 1 else ''}.")
    else:
        print("  No issues found — everything looks clean.")
    print()
    return 0


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

    if mode == "repair":
        return _run_repair()

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
