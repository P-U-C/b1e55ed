"""engine.cli.doctor

`b1e55ed doctor` — system diagnostic command.

Runs tiered health checks:
  T0: Preflight (env, deps, config, DB, identity, kill switch)
  T1: Component instantiation (producers, orchestrator, OMS, dashboard)
  T2: Pipeline smoke (signal ingestion, brain cycle, outcomes, learning)
  T3: Live checks (API health, auth, dashboard, kill switch, staleness)
  T4: Integration flywheel (temp DB, full cycle, paper trades, karma)

Flags:
  --tier 0|1|2|3|4  Run up to this tier (default: 2)
  --json            Machine-readable JSON output
  --fix             Auto-remediate where possible
  --api-port        API port for T3 checks (default: 5050)
  --dashboard-port  Dashboard port for T3 checks (default: 5051)
  --auth-token      Auth token for T3 API checks
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from engine.doctor.tier0 import CheckResult


def build_doctor_parser(sub: argparse._SubParsersAction) -> None:
    """Register the ``doctor`` subcommand on the CLI parser."""
    p = sub.add_parser("doctor", help="Run system diagnostics (tiers 0-4)")
    p.add_argument(
        "--tier",
        type=int,
        default=2,
        choices=[0, 1, 2, 3, 4],
        help="Maximum tier to run (0=preflight, 1=components, 2=pipeline, 3=live, 4=flywheel). Default: 2",
    )
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    p.add_argument("--fix", action="store_true", help="Auto-remediate fixable issues.")
    p.add_argument("--api-port", type=int, default=5050, help="API port for T3 checks (default: 5050)")
    p.add_argument("--dashboard-port", type=int, default=5051, help="Dashboard port for T3 checks (default: 5051)")
    p.add_argument("--auth-token", default=None, help="Auth token for T3 API checks")


def _color(text: str, color: str) -> str:
    """ANSI color wrapper. Falls back to plain text if not a TTY."""
    if not sys.stdout.isatty():
        return text
    codes = {"green": "\033[32m", "yellow": "\033[33m", "red": "\033[31m", "bold": "\033[1m", "reset": "\033[0m"}
    return f"{codes.get(color, '')}{text}{codes.get('reset', '')}"


def _icon(status: str) -> str:
    return {"pass": "✅", "warn": "⚠️ ", "fail": "❌"}.get(status, "?")


def _auto_fix(results: list[CheckResult]) -> list[str]:
    """Attempt auto-remediation for known fixable issues."""
    actions: list[str] = []
    for r in results:
        if r.name == "kill_switch" and r.status == "warn" and "level" in r.message:
            try:
                from engine.core.database import Database
                from engine.core.events import EventType
                from engine.core.paths import data_dir

                db_path = data_dir() / "brain.db"
                if db_path.exists():
                    db = Database(db_path)
                    try:
                        payload = {
                            "level": 0,
                            "previous_level": -1,
                            "reason": "doctor --fix: reset to SAFE",
                            "auto": True,
                            "actor": "doctor",
                        }
                        db.append_event(event_type=EventType.KILL_SWITCH_V1, payload=payload, source="cli.doctor")
                        r.status = "pass"
                        r.message = "Kill switch: SAFE (level 0) — reset by doctor --fix"
                        r.remediation = None
                        actions.append("Reset kill switch to level 0")
                    finally:
                        db.close()
            except Exception as e:
                actions.append(f"Kill switch fix failed: {e}")
    return actions


def run_doctor(args: argparse.Namespace) -> int:
    """Entry point for ``b1e55ed doctor``."""
    from engine import __version__

    tier = int(getattr(args, "tier", 2))
    as_json = bool(getattr(args, "json", False))
    do_fix = bool(getattr(args, "fix", False))

    all_results: dict[str, list[CheckResult]] = {}
    fix_actions: list[str] = []

    # T0 — Preflight
    from engine.doctor.tier0 import run_tier0

    all_results["T0 Preflight"] = run_tier0()
    if do_fix:
        fix_actions.extend(_auto_fix(all_results["T0 Preflight"]))

    # T1 — Components
    if tier >= 1:
        from engine.doctor.tier1 import run_tier1

        all_results["T1 Components"] = run_tier1()
        if do_fix:
            fix_actions.extend(_auto_fix(all_results["T1 Components"]))

    # T2 — Pipeline
    if tier >= 2:
        from engine.doctor.tier2 import run_tier2

        all_results["T2 Pipeline"] = run_tier2()
        if do_fix:
            fix_actions.extend(_auto_fix(all_results["T2 Pipeline"]))

    # T3 — Live checks
    if tier >= 3:
        from engine.doctor.tier3 import run_tier3

        all_results["T3 Live"] = run_tier3(
            api_port=int(getattr(args, "api_port", 5050)),
            dashboard_port=int(getattr(args, "dashboard_port", 5051)),
            auth_token=getattr(args, "auth_token", None),
        )
        if do_fix:
            fix_actions.extend(_auto_fix(all_results["T3 Live"]))

    # T4 — Integration flywheel
    if tier >= 4:
        from engine.doctor.tier4 import run_tier4

        all_results["T4 Flywheel"] = run_tier4()
        if do_fix:
            fix_actions.extend(_auto_fix(all_results["T4 Flywheel"]))

    # Score
    total = sum(len(v) for v in all_results.values())
    passes = sum(1 for checks in all_results.values() for c in checks if c.status == "pass")
    warns = sum(1 for checks in all_results.values() for c in checks if c.status == "warn")
    fails = sum(1 for checks in all_results.values() for c in checks if c.status == "fail")

    if as_json:
        output: dict[str, Any] = {
            "version": __version__,
            "tier": tier,
            "score": {"total": total, "pass": passes, "warn": warns, "fail": fails},
            "fix_actions": fix_actions,
            "tiers": {},
        }
        for tier_name, checks in all_results.items():
            output["tiers"][tier_name] = [
                {
                    "name": c.name,
                    "status": c.status,
                    "message": c.message,
                    "remediation": c.remediation,
                }
                for c in checks
            ]
        print(json.dumps(output, indent=2, default=str))
    else:
        print()
        print(f"  {_color('b1e55ed doctor', 'bold')} v{__version__}")
        print()
        for tier_name, checks in all_results.items():
            print(f"  {_color(tier_name, 'bold')}")
            for c in checks:
                icon = _icon(c.status)
                msg = c.message
                if c.status == "warn":
                    msg = _color(msg, "yellow")
                elif c.status == "fail":
                    msg = _color(msg, "red")
                print(f"    {icon} {msg}")
                if c.remediation and c.status != "pass":
                    print(f"       → {c.remediation}")
            print()

        if fix_actions:
            print(f"  {_color('Auto-fix actions:', 'bold')}")
            for a in fix_actions:
                print(f"    🔧 {a}")
            print()

        print("  " + "═" * 42)
        score_str = f"Score: {passes}/{total}"
        detail_parts = []
        if warns > 0:
            detail_parts.append(f"{warns} warning{'s' if warns != 1 else ''}")
        if fails > 0:
            detail_parts.append(f"{fails} error{'s' if fails != 1 else ''}")
        detail = f" — {', '.join(detail_parts)}" if detail_parts else " — all clear"
        print(f"  {score_str}{detail}")
        if (fails > 0 or warns > 0) and not do_fix:
            print("  Run with --fix to auto-remediate where possible.")
        print()

    return 1 if fails > 0 else 0
