"""engine.cli

Command line interface entry point for b1e55ed.

Design constraints:
- argparse-based.
- Lazy imports: do not import heavy dependencies at parse time.

The hex is blessed: 0xb1e55ed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

EPILOG = "The code remembers. The hex is blessed: 0xb1e55ed."


def _json_dumps(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    if not rows:
        return

    widths = [len(h) for h in headers]
    for r in rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(r: list[str]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(r))

    print(fmt_row(headers))
    print(fmt_row(["-" * w for w in widths]))
    for r in rows:
        print(fmt_row(r))


@dataclass(frozen=True)
class CliContext:
    repo_root: Path


def _repo_root_from_cwd() -> Path:
    return Path.cwd()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="b1e55ed",
        description="Sovereign trading intelligence with compound learning.",
        epilog=EPILOG,
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print version and exit.",
    )

    sub = parser.add_subparsers(dest="command")

    p_setup = sub.add_parser("setup", help="Interactive onboarding and first-run configuration")
    p_setup.add_argument(
        "--preset",
        choices=["conservative", "balanced", "degen"],
        default=None,
        help="Config preset to apply.",
    )
    p_setup.add_argument(
        "--non-interactive",
        action="store_true",
        help="Run setup without prompts (uses env vars).",
    )

    p_brain = sub.add_parser("brain", help="Run one brain cycle")
    p_brain.add_argument(
        "--full",
        action="store_true",
        help="Run a full cycle (includes slower producers).",
    )
    p_brain.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )

    p_signal = sub.add_parser("signal", help="Ingest operator intel as a curator signal")
    p_signal.add_argument(
        "rest",
        nargs=argparse.REMAINDER,
        help='Signal text or subcommand, e.g. b1e55ed signal "BTC looking strong" OR b1e55ed signal add --file note.txt',
    )
    p_signal.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )

    p_alerts = sub.add_parser("alerts", help="List active alerts")
    p_alerts.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )

    p_positions = sub.add_parser("positions", help="List open positions with P&L")
    p_positions.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )

    p_ks = sub.add_parser("kill-switch", help="Show or set kill switch level")
    p_ks.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )
    ks_sub = p_ks.add_subparsers(dest="kill_switch_cmd")
    p_ks_set = ks_sub.add_parser("set", help="Set kill switch level (operator override)")
    p_ks_set.add_argument("level", type=int, help="Kill switch level (0-4)")
    p_ks_set.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )

    p_health = sub.add_parser("health", help="System health check")
    p_health.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON (default).",
    )

    p_keys = sub.add_parser("keys", help="Manage API keys")
    keys_sub = p_keys.add_subparsers(dest="keys_cmd")

    p_keys_list = keys_sub.add_parser("list", help="Show all known key slots")
    p_keys_list.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    p_keys_set = keys_sub.add_parser("set", help="Store a key")
    p_keys_set.add_argument("name")
    p_keys_set.add_argument("value")
    p_keys_set.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    p_keys_remove = keys_sub.add_parser("remove", help="Remove a key")
    p_keys_remove.add_argument("name")
    p_keys_remove.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    p_keys_test = keys_sub.add_parser("test", help="Verify configured keys against live APIs")
    p_keys_test.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    p_api = sub.add_parser("api", help="Start FastAPI server")
    p_api.add_argument("--host", default=None)
    p_api.add_argument("--port", type=int, default=None)

    p_dash = sub.add_parser("dashboard", help="Start dashboard server")
    p_dash.add_argument("--host", default=None)
    p_dash.add_argument("--port", type=int, default=None)

    sub.add_parser("status", help="Print system status")

    return parser


def _print_version() -> None:
    from engine import __version__

    print(f"b1e55ed v{__version__} (0xb1e55ed)")


def _cmd_setup(ctx: CliContext, args: argparse.Namespace) -> int:
    # Lazy imports
    from engine.core.database import Database
    from engine.security.identity import ensure_identity
    from engine.security.keystore import Keystore

    repo_root = ctx.repo_root

    banner = "\n0xb1e55ed\nb1e55ed setup\n\nA system without memory repeats mistakes.\n"
    print(banner)

    config_dir = repo_root / "config"
    presets_dir = config_dir / "presets"
    if not presets_dir.exists():
        print(f"error: presets directory not found: {presets_dir}", file=sys.stderr)
        return 2

    user_cfg_path = config_dir / "user.yaml"

    non_interactive = bool(args.non_interactive) or os.getenv("B1E55ED_NONINTERACTIVE") in {
        "1",
        "true",
        "TRUE",
        "yes",
        "YES",
    }

    preset = args.preset or os.getenv("B1E55ED_PRESET")

    if not preset and not non_interactive:
        preset = _prompt_choice(
            "Choose a preset",
            choices=["conservative", "balanced", "degen"],
            default="balanced",
        )

    preset = preset or "balanced"

    preset_path = presets_dir / f"{preset}.yaml"
    if not preset_path.exists():
        print(f"error: preset not found: {preset_path}", file=sys.stderr)
        return 2

    _write_user_config(user_cfg_path=user_cfg_path, preset=preset)

    # Secrets: best-effort via keystore. If no encrypted tier is available, fall back to env.
    keystore = Keystore.default()

    def ask_or_env(prompt: str, env_name: str) -> str | None:
        v = os.getenv(env_name)
        if v:
            return v
        if non_interactive:
            return None
        return _prompt_optional(prompt)

    # Exchange
    hl_key = ask_or_env("Hyperliquid API key", "B1E55ED_HYPERLIQUID_API_KEY")
    hl_secret = ask_or_env("Hyperliquid API secret", "B1E55ED_HYPERLIQUID_API_SECRET")
    if hl_key:
        keystore.set("hyperliquid.api_key", hl_key)
    if hl_secret:
        keystore.set("hyperliquid.api_secret", hl_secret)

    # Data
    allium = ask_or_env("Allium API key", "B1E55ED_ALLIUM_API_KEY")
    nansen = ask_or_env("Nansen API key", "B1E55ED_NANSEN_API_KEY")
    if allium:
        keystore.set("allium.api_key", allium)
    if nansen:
        keystore.set("nansen.api_key", nansen)

    # Social
    reddit = ask_or_env("Reddit client id", "B1E55ED_REDDIT_CLIENT_ID")
    apify = ask_or_env("Apify token", "B1E55ED_APIFY_API_KEY")
    if reddit:
        keystore.set("reddit.client_id", reddit)
    if apify:
        keystore.set("apify.token", apify)

    identity = ensure_identity()

    # Initialize database
    data_dir = repo_root / "data"
    db_path = data_dir / "brain.db"
    _ = Database(db_path)

    print("\nStatus summary")
    print(f"- repo_root: {repo_root}")
    print(f"- config: {user_cfg_path}")
    print(f"- identity: {identity.path}")
    print(f"- keystore: {keystore.describe()}")
    print(f"- db: {db_path}")

    print("\nYou're blessed. Run `b1e55ed brain` to start.")
    return 0


def _cmd_brain(ctx: CliContext, args: argparse.Namespace) -> int:
    # Lazy import: brain pipeline can be heavy.
    from engine.core.config import Config
    from engine.core.database import Database
    from engine.security.identity import ensure_identity

    repo_root = ctx.repo_root
    cfg_path = repo_root / "config" / "user.yaml"
    config = Config.from_yaml(cfg_path) if cfg_path.exists() else Config.from_repo_defaults(repo_root)

    db = Database(repo_root / "data" / "brain.db")
    identity = ensure_identity()

    try:
        # Optional: run producers prior to orchestration.
        import logging
        from dataclasses import asdict

        from engine.core.client import DataClient
        from engine.core.metrics import REGISTRY
        from engine.producers.base import ProducerContext
        from engine.producers.registry import discover, get_producer, list_producers

        discover()
        names = list_producers()
        if not bool(args.full):

            def is_fast(n: str) -> bool:
                cls = get_producer(n)
                s = str(getattr(cls, "schedule", ""))
                return s.startswith("*/1") or s == "continuous"

            names = [n for n in names if is_fast(n)]

        logger = logging.getLogger("b1e55ed.producers")
        client = DataClient()
        pctx = ProducerContext(config=config, db=db, client=client, metrics=REGISTRY, logger=logger)
        producer_results = []
        for n in names:
            cls = get_producer(n)
            res = cls(pctx).run()
            producer_results.append({"name": n, **res.model_dump(mode="json")})

        from engine.brain.orchestrator import BrainOrchestrator

        orchestrator = BrainOrchestrator(config=config, db=db, identity=identity.identity)
        result = orchestrator.run_cycle(symbols=config.universe.symbols)

        if bool(args.json):
            payload = {"cycle": asdict(result), "producers": producer_results}
            print(_json_dumps(payload))
        else:
            print(result)

        try:
            import asyncio

            asyncio.run(client.aclose())
        except Exception:  # noqa: BLE001
            pass
        return 0
    except Exception as e:
        print(f"brain cycle failed: {e}", file=sys.stderr)
        return 1


def _extract_symbols(text: str, *, universe: list[str]) -> list[str]:
    import re

    if not text:
        return []
    u = {s.upper() for s in universe}
    found: list[str] = []
    for m in re.findall(r"\$?[A-Za-z]{2,8}", text):
        sym = m.upper().lstrip("$")
        if sym in u and sym not in found:
            found.append(sym)
    return found


def _cmd_signal(ctx: CliContext, args: argparse.Namespace) -> int:
    from engine.core.config import Config
    from engine.core.database import Database
    from engine.core.events import CuratorSignalPayload, EventType, compute_dedupe_key
    from engine.security.identity import ensure_identity

    repo_root = ctx.repo_root
    cfg_path = repo_root / "config" / "user.yaml"
    config = Config.from_yaml(cfg_path) if cfg_path.exists() else Config.from_repo_defaults(repo_root)

    db = Database(repo_root / "data" / "brain.db")
    identity = ensure_identity()

    rest = list(getattr(args, "rest", []) or [])

    text: str | None = None
    if rest and rest[0] == "add":
        subp = argparse.ArgumentParser(prog="b1e55ed signal add", add_help=False)
        subp.add_argument("--file", required=True)
        try:
            ns = subp.parse_args(rest[1:])
        except SystemExit:
            print("error: usage: b1e55ed signal add --file <path>", file=sys.stderr)
            return 2

        fp = Path(str(ns.file))
        if not fp.exists():
            print(f"error: file not found: {fp}", file=sys.stderr)
            return 2
        text = fp.read_text(encoding="utf-8")
    else:
        # remainder is treated as a free-form text (shell quoting is handled by the OS)
        text = " ".join(rest).strip() if rest else None

    if not text or not str(text).strip():
        print("error: signal text required", file=sys.stderr)
        return 2

    raw = str(text).strip()
    syms = _extract_symbols(raw, universe=config.universe.symbols)
    if not syms:
        syms = ["GLOBAL"]

    events = []
    for sym in syms:
        payload_obj = CuratorSignalPayload(
            symbol=sym,
            direction="neutral",
            conviction=0.0,
            rationale=raw,
            source=f"operator:{identity.identity.node_id}",
        )
        payload = payload_obj.model_dump(mode="json")
        ev = db.append_event(
            event_type=EventType.SIGNAL_CURATOR_V1,
            payload=payload,
            source="cli.signal",
            dedupe_key=compute_dedupe_key(EventType.SIGNAL_CURATOR_V1, payload),
        )
        events.append({"id": ev.id, "type": str(ev.type), "ts": ev.ts.isoformat(), "payload": ev.payload})

    out = {"status": "ok", "events": events}
    if bool(getattr(args, "json", False)):
        print(_json_dumps(out))
    else:
        print(f"signal ingested: {len(events)} event(s)")
        for ev in events:
            print(f"- {ev['id']} {ev['payload'].get('symbol')}")
    return 0


def _latest_mark_prices(db) -> dict[str, float]:
    from engine.core.events import EventType

    prices: dict[str, float] = {}
    evs = db.get_events(event_type=EventType.SIGNAL_PRICE_WS_V1, limit=500)
    for ev in evs:
        sym = str(ev.payload.get("symbol") or "").upper()
        px = ev.payload.get("price")
        if sym and px is not None and sym not in prices:
            prices[sym] = float(px)
    return prices


def _cmd_positions(ctx: CliContext, args: argparse.Namespace) -> int:
    from engine.core.database import Database
    from engine.execution.pnl import PnLTracker

    repo_root = ctx.repo_root
    db = Database(repo_root / "data" / "brain.db")
    tracker = PnLTracker(db)

    mark = _latest_mark_prices(db)
    rows = db.conn.execute(
        "SELECT id, asset, direction, entry_price, size_notional, leverage, opened_at FROM positions WHERE status = 'open' ORDER BY opened_at DESC"
    ).fetchall()

    out = []
    for r in rows:
        pid = str(r[0])
        sym = str(r[1]).upper()
        mp = mark.get(sym)
        unreal = tracker.unrealized_usd(position_id=pid, mark_price=float(mp)) if mp is not None else None
        out.append(
            {
                "id": pid,
                "asset": sym,
                "direction": str(r[2]),
                "entry_price": float(r[3]),
                "size_notional": float(r[4]),
                "leverage": float(r[5] or 1.0),
                "opened_at": str(r[6]),
                "mark_price": float(mp) if mp is not None else None,
                "unrealized_pnl_usd": float(unreal) if unreal is not None else None,
            }
        )

    if bool(getattr(args, "json", False)):
        print(_json_dumps(out))
        return 0

    print("open positions")
    if not out:
        print("(none)")
        return 0

    table_rows: list[list[str]] = []
    for p in out:
        pnl = p["unrealized_pnl_usd"]
        table_rows.append(
            [
                p["asset"],
                p["direction"],
                f"{p['entry_price']:.2f}",
                f"{p['mark_price']:.2f}" if p["mark_price"] is not None else "-",
                f"{p['size_notional']:.2f}",
                f"{pnl:+.2f}" if pnl is not None else "-",
                p["id"][:8],
            ]
        )

    _print_table(["asset", "dir", "entry", "mark", "notional", "pnl", "id"], table_rows)
    return 0


def _kill_switch_state(db) -> dict[str, object]:
    from engine.brain.kill_switch import LEVEL_MESSAGES, KillSwitchLevel
    from engine.core.events import EventType

    evs = db.get_events(event_type=EventType.KILL_SWITCH_V1, limit=1)
    if not evs:
        return {"level": 0, "reason": LEVEL_MESSAGES.get(KillSwitchLevel.SAFE, "Normal operation."), "ts": None}

    ev = evs[0]
    lvl = int(ev.payload.get("level") or 0)
    reason = str(ev.payload.get("reason") or "")
    return {"level": lvl, "reason": reason, "ts": ev.ts.isoformat()}


def _cmd_kill_switch(ctx: CliContext, args: argparse.Namespace) -> int:
    from engine.core.database import Database
    from engine.core.events import EventType

    repo_root = ctx.repo_root
    db = Database(repo_root / "data" / "brain.db")

    if getattr(args, "kill_switch_cmd", None) == "set":
        lvl = int(args.level)
        if lvl < 0 or lvl > 4:
            print("error: level must be 0-4", file=sys.stderr)
            return 2
        prev = _kill_switch_state(db)
        payload = {
            "level": lvl,
            "previous_level": int(prev.get("level") or 0),
            "reason": f"manual:{lvl}",
            "auto": False,
            "actor": "operator",
        }
        ev = db.append_event(event_type=EventType.KILL_SWITCH_V1, payload=payload, source="cli.kill_switch")
        out = {"status": "ok", "event_id": ev.id, "payload": payload}
        if bool(getattr(args, "json", False)):
            print(_json_dumps(out))
        else:
            print(f"kill switch set to {lvl} (event {ev.id})")
        return 0

    state = _kill_switch_state(db)
    if bool(getattr(args, "json", False)):
        print(_json_dumps(state))
    else:
        print(f"kill switch: L{state['level']}\nreason: {state['reason']}")
    return 0


def _cmd_alerts(ctx: CliContext, args: argparse.Namespace) -> int:
    from engine.core.database import Database

    repo_root = ctx.repo_root
    db = Database(repo_root / "data" / "brain.db")

    alerts: list[dict[str, object]] = []

    # Kill switch alert
    ks = _kill_switch_state(db)
    if int(ks.get("level") or 0) > 0:
        alerts.append(
            {
                "type": "kill_switch",
                "severity": int(ks["level"]),
                "detail": ks.get("reason"),
                "ts": ks.get("ts"),
            }
        )

    # Producer health
    rows = db.conn.execute(
        "SELECT name, domain, consecutive_failures, last_error, last_run_at FROM producer_health WHERE consecutive_failures > 0 OR last_error IS NOT NULL"
    ).fetchall()
    for r in rows:
        alerts.append(
            {
                "type": "producer",
                "severity": int(r[2] or 1),
                "detail": f"{r[0]} ({r[1]}): {r[3]}",
                "ts": str(r[4] or ""),
            }
        )

    # Position stops/targets
    pos = db.conn.execute(
        "SELECT asset, stop_loss, take_profit, opened_at, id FROM positions WHERE status = 'open' AND (stop_loss IS NOT NULL OR take_profit IS NOT NULL)"
    ).fetchall()
    for r in pos:
        detail = f"{str(r[0]).upper()} stop={r[1] if r[1] is not None else '-'} tp={r[2] if r[2] is not None else '-'}"
        alerts.append(
            {
                "type": "position",
                "severity": 1,
                "detail": detail,
                "ts": str(r[3]),
                "position_id": str(r[4]),
            }
        )

    if bool(getattr(args, "json", False)):
        print(_json_dumps(alerts))
        return 0

    print("active alerts")
    if not alerts:
        print("(none)")
        return 0

    table_rows = [[str(a.get("type")), str(a.get("severity")), str(a.get("detail")), str(a.get("ts") or "")] for a in alerts]
    _print_table(["type", "sev", "detail", "ts"], table_rows)
    return 0


def _cmd_health(ctx: CliContext, args: argparse.Namespace) -> int:
    import time

    from engine.core.config import Config
    from engine.core.database import Database
    from engine.security.identity import identity_status
    from engine.security.keystore import Keystore

    _ = args  # unused, reserved

    start = time.monotonic()
    repo_root = ctx.repo_root

    cfg_user = repo_root / "config" / "user.yaml"
    cfg_path = cfg_user if cfg_user.exists() else repo_root / "config" / "default.yaml"

    cfg_ok = False
    cfg_error = None
    try:
        _ = Config.from_yaml(cfg_path) if cfg_path.exists() else None
        cfg_ok = cfg_path.exists()
    except Exception as e:  # noqa: BLE001
        cfg_error = str(e)

    db_path = repo_root / "data" / "brain.db"
    db_ok = db_path.exists()

    chain_ok = None
    if db_ok:
        try:
            db = Database(db_path)
            chain_ok = bool(db.verify_hash_chain(fast=True))
        except Exception:  # noqa: BLE001
            chain_ok = False

    ks = Keystore.default()

    payload = {
        "ok": bool(cfg_ok) and bool(db_ok) and (chain_ok is not False),
        "uptime_s": float(time.monotonic() - start),
        "config": {"path": str(cfg_path), "present": bool(cfg_path.exists()), "ok": bool(cfg_ok), "error": cfg_error},
        "db": {"path": str(db_path), "present": bool(db_ok), "hash_chain_ok": chain_ok},
        "identity": identity_status(),
        "keystore": {"describe": ks.describe()},
    }

    # health always returns JSON (suitable for cron/heartbeat)
    print(_json_dumps(payload))
    return 0


def _cmd_keys(ctx: CliContext, args: argparse.Namespace) -> int:
    from engine.cli_keys import cmd_keys_list, cmd_keys_remove, cmd_keys_set, cmd_keys_test
    from engine.security.keystore import Keystore

    keystore = Keystore.default()

    sub = getattr(args, "keys_cmd", None)
    if not sub:
        print("error: missing keys subcommand (list/set/remove/test)", file=sys.stderr)
        return 2

    as_json = bool(getattr(args, "json", False))

    if sub == "list":
        return int(cmd_keys_list(keystore=keystore, as_json=as_json))
    if sub == "set":
        return int(cmd_keys_set(keystore=keystore, name=str(args.name), value=str(args.value), as_json=as_json))
    if sub == "remove":
        return int(cmd_keys_remove(keystore=keystore, name=str(args.name), as_json=as_json))
    if sub == "test":
        return int(cmd_keys_test(keystore=keystore, as_json=as_json))

    print(f"error: unknown keys subcommand: {sub}", file=sys.stderr)
    return 2


def _cmd_api(ctx: CliContext, args: argparse.Namespace) -> int:
    from engine.core.config import Config

    repo_root = ctx.repo_root
    cfg_path = repo_root / "config" / "user.yaml"
    config = Config.from_yaml(cfg_path) if cfg_path.exists() else Config.from_repo_defaults(repo_root)

    host = args.host or config.api.host
    port = args.port or config.api.port

    import uvicorn

    uvicorn.run("api.main:app", host=host, port=port, reload=False)
    return 0


def _cmd_dashboard(ctx: CliContext, args: argparse.Namespace) -> int:
    from engine.core.config import Config

    repo_root = ctx.repo_root
    cfg_path = repo_root / "config" / "user.yaml"
    config = Config.from_yaml(cfg_path) if cfg_path.exists() else Config.from_repo_defaults(repo_root)

    host = args.host or config.dashboard.host
    port = args.port or config.dashboard.port

    import uvicorn

    uvicorn.run("dashboard.app:app", host=host, port=port, reload=False)
    return 0


def _cmd_status(ctx: CliContext, args: argparse.Namespace) -> int:
    import time

    from engine.core.config import Config
    from engine.security.identity import identity_status
    from engine.security.keystore import Keystore

    _ = args  # reserved

    repo_root = ctx.repo_root

    start = time.monotonic()

    cfg_user = repo_root / "config" / "user.yaml"
    cfg = cfg_user if cfg_user.exists() else repo_root / "config" / "default.yaml"

    try:
        _ = Config.from_yaml(cfg) if cfg.exists() else None
        config_status = str(cfg)
    except Exception as e:
        config_status = f"{cfg} (error: {e})"

    db_path = repo_root / "data" / "brain.db"
    db_status = "present" if db_path.exists() else "missing"

    ks = Keystore.default()

    print("b1e55ed status")
    print(f"- uptime: {time.monotonic() - start:.3f}s")
    print(f"- config: {config_status}")
    print(f"- db: {db_path} ({db_status})")
    print(f"- identity: {identity_status()}")
    print(f"- keystore: {ks.describe()}")

    health = "blessed" if cfg.exists() else "degraded"
    print(f"- system health: {health}")
    return 0


def _prompt_choice(prompt: str, *, choices: list[str], default: str) -> str:
    choice_set = {c.lower(): c for c in choices}
    while True:
        raw = input(f"{prompt} [{'/'.join(choices)}] (default: {default}): ").strip()
        if not raw:
            return default
        v = choice_set.get(raw.lower())
        if v is not None:
            return v
        print(f"Invalid choice: {raw}")


def _prompt_optional(prompt: str) -> str | None:
    raw = input(f"{prompt} (enter to skip): ").strip()
    return raw or None


def _write_user_config(*, user_cfg_path: Path, preset: str) -> None:
    user_cfg_path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(
        [
            "# Generated by `b1e55ed setup`",
            f"preset: {preset}",
            "",
        ]
    )
    user_cfg_path.write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        _print_version()
        return 0

    if not args.command:
        parser.print_help()
        return 2

    ctx = CliContext(repo_root=_repo_root_from_cwd())

    dispatch: dict[str, Callable[[CliContext, argparse.Namespace], int]] = {
        "setup": _cmd_setup,
        "brain": _cmd_brain,
        "signal": _cmd_signal,
        "alerts": _cmd_alerts,
        "positions": _cmd_positions,
        "kill-switch": _cmd_kill_switch,
        "health": _cmd_health,
        "keys": _cmd_keys,
        "api": _cmd_api,
        "dashboard": _cmd_dashboard,
        "status": _cmd_status,
    }

    fn = dispatch.get(str(args.command))
    if fn is None:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 2

    return int(fn(ctx, args))


if __name__ == "__main__":
    raise SystemExit(main())
