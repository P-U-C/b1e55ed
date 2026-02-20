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
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:  # pragma: no cover
    from engine.core.config import Config
    from engine.core.contributors import ContributorRegistry
    from engine.core.database import Database


EPILOG = "The code remembers. The hex is blessed: 0xb1e55ed."


def _json_dumps(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def _safe_int(v: object) -> int:
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str):
        try:
            return int(v)
        except ValueError:
            return 0
    return 0


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


def _load_config(ctx: CliContext) -> Config | None:
    try:
        from engine.core.config import Config

        user_path = ctx.repo_root / "config" / "user.yaml"
        if user_path.exists():
            return Config.from_yaml(user_path)
        return Config.from_repo_defaults(ctx.repo_root)
    except Exception:  # noqa: BLE001
        return None


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
    # NOTE: "rest" is remainder to allow flexible ordering of flags and subcommand-like forms.
    # We re-parse inside _cmd_signal() to support `signal add --file ...` with flags placed after `add`.
    p_signal.add_argument(
        "rest",
        nargs=argparse.REMAINDER,
        help='Signal text or subcommand, e.g. b1e55ed signal "BTC looking strong" OR b1e55ed signal add --file note.txt',
    )
    p_signal.add_argument(
        "--symbols",
        default=None,
        help='Comma-separated symbols override, e.g. --symbols "BTC,ETH"',
    )
    p_signal.add_argument(
        "--source",
        default=None,
        help='Signal source tag, e.g. --source "operator"',
    )
    p_signal.add_argument(
        "--direction",
        choices=["bullish", "bearish", "neutral"],
        default=None,
        help="Signal direction.",
    )
    p_signal.add_argument(
        "--conviction",
        type=float,
        default=None,
        help="Conviction score (0-10).",
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
    p_alerts.add_argument(
        "--since",
        type=int,
        default=None,
        help="Only include alerts newer than this many minutes.",
    )

    p_positions = sub.add_parser("positions", help="List open positions with P&L")
    p_positions.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )

    p_producers = sub.add_parser("producers", help="Register and manage producers")
    prod_sub = p_producers.add_subparsers(dest="producers_cmd")

    p_prod_reg = prod_sub.add_parser("register", help="Register a producer")
    p_prod_reg.add_argument("--name", required=True)
    p_prod_reg.add_argument("--domain", required=True)
    p_prod_reg.add_argument("--endpoint", required=True)
    p_prod_reg.add_argument("--schedule", default="*/15 * * * *")

    p_prod_list = prod_sub.add_parser("list", help="List registered producers")
    p_prod_list.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    p_prod_rm = prod_sub.add_parser("remove", help="Remove a producer")
    p_prod_rm.add_argument("--name", required=True)

    p_contrib = sub.add_parser("contributors", help="Manage contributors and reputation")
    contrib_sub = p_contrib.add_subparsers(dest="contributors_cmd")

    p_contrib_list = contrib_sub.add_parser("list", help="List contributors")
    p_contrib_list.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    p_contrib_reg = contrib_sub.add_parser("register", help="Register a contributor")
    p_contrib_reg.add_argument("--name", required=True)
    p_contrib_reg.add_argument("--role", required=True, choices=["operator", "agent", "tester", "curator"])
    p_contrib_reg.add_argument("--node-id", default=None)
    p_contrib_reg.add_argument(
        "--attest",
        action="store_true",
        help="Create an off-chain EAS attestation (requires eas.enabled + eas.attester_private_key).",
    )

    p_contrib_rm = contrib_sub.add_parser("remove", help="Remove a contributor")
    p_contrib_rm.add_argument("--id", required=True)

    p_contrib_score = contrib_sub.add_parser("score", help="Compute contributor score")
    p_contrib_score.add_argument("--id", required=True)
    p_contrib_score.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    p_contrib_lb = contrib_sub.add_parser("leaderboard", help="Show contributor leaderboard")
    p_contrib_lb.add_argument("--limit", type=int, default=20)
    p_contrib_lb.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    p_webhooks = sub.add_parser("webhooks", help="Manage outbound webhook subscriptions")
    wh_sub = p_webhooks.add_subparsers(dest="webhooks_cmd")

    p_wh_add = wh_sub.add_parser("add", help="Add a webhook subscription")
    p_wh_add.add_argument("url", help="Webhook URL")
    p_wh_add.add_argument(
        "--events",
        required=True,
        help='Comma-separated event globs, e.g. "alert.*,system.kill_switch.*"',
    )

    p_wh_list = wh_sub.add_parser("list", help="List webhook subscriptions")
    p_wh_list.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    p_wh_remove = wh_sub.add_parser("remove", help="Remove a webhook subscription")
    p_wh_remove.add_argument("id", type=int, help="Subscription id")

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

    identity_parser = sub.add_parser("identity", help="Identity management")
    identity_sub = identity_parser.add_subparsers(dest="identity_action")

    forge_parser = identity_sub.add_parser("forge", help="Forge a new 0xb1e55ed identity")
    forge_parser.add_argument("--threads", type=int, default=None)
    forge_parser.add_argument("--json", action="store_true")

    show_parser = identity_sub.add_parser("show", help="Show current identity")
    show_parser.add_argument("--json", action="store_true")

    p_api = sub.add_parser("api", help="Start FastAPI server")
    p_api.add_argument("--host", default=None)
    p_api.add_argument("--port", type=int, default=None)

    p_dash = sub.add_parser("dashboard", help="Start dashboard server")
    p_dash.add_argument("--host", default=None)
    p_dash.add_argument("--port", type=int, default=None)

    p_eas = sub.add_parser("eas", help="Ethereum Attestation Service (EAS) utilities")
    eas_sub = p_eas.add_subparsers(dest="eas_cmd")

    p_eas_status = eas_sub.add_parser("status", help="Show EAS config and schema status")
    p_eas_status.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    p_eas_verify = eas_sub.add_parser("verify", help="Verify an off-chain attestation by UID")
    p_eas_verify.add_argument("--uid", required=True, help="Attestation UID")
    p_eas_verify.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    sub.add_parser("status", help="Print system status")

    # -- replay --
    p_replay = sub.add_parser("replay", help="Rebuild projections from event replay")
    p_replay.add_argument("--from", dest="from_id", help="Start from event ID (inclusive)")
    p_replay.add_argument("--to", dest="to_id", help="End at event ID (inclusive)")
    p_replay.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    # -- integrity --
    p_integrity = sub.add_parser("integrity", help="Verify event chain integrity and projection consistency")
    p_integrity.add_argument("--fast", action="store_true", help="Check only recent events")
    p_integrity.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

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
        from engine.producers.base import BaseProducer, ProducerContext
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
        producer_results: list[dict[str, object]] = []
        for n in names:
            from typing import cast

            cls = get_producer(n)
            producer_cls = cast(type[BaseProducer], cls)
            producer = producer_cls(pctx)
            res = producer.run()
            producer_results.append(
                {
                    "name": n,
                    "events_published": res.events_published,
                    "errors": list(res.errors),
                    "duration_ms": res.duration_ms,
                    "timestamp": res.timestamp.isoformat(),
                    "staleness_ms": res.staleness_ms,
                    "health": str(res.health),
                }
            )

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

    # We accept flags both before and after the free-form text / `add` subcommand.
    # The top-level argparse only knows about `args.*` values. Any flags placed after
    # `add` end up in `args.rest`, so we re-parse them here.
    rest = list(getattr(args, "rest", []) or [])

    sigp = argparse.ArgumentParser(prog="b1e55ed signal", add_help=False)
    sigp.add_argument("--symbols", default=None)
    sigp.add_argument("--source", default=None)
    sigp.add_argument("--direction", choices=["bullish", "bearish", "neutral"], default=None)
    sigp.add_argument("--conviction", type=float, default=None)
    sigp.add_argument("--json", action="store_true")

    ns_flags, remaining = sigp.parse_known_args(rest)

    # Merge: explicit flags in `rest` should override top-level parsed flags.
    symbols_raw = ns_flags.symbols if ns_flags.symbols is not None else getattr(args, "symbols", None)
    source_raw = ns_flags.source if ns_flags.source is not None else getattr(args, "source", None)
    direction = ns_flags.direction if ns_flags.direction is not None else getattr(args, "direction", None)
    conviction = ns_flags.conviction if ns_flags.conviction is not None else getattr(args, "conviction", None)
    as_json = bool(getattr(args, "json", False) or bool(ns_flags.json))

    if direction is None:
        direction = "neutral"
    if conviction is None:
        conviction = 0.0

    if conviction < 0 or conviction > 10:
        print("error: conviction must be 0-10", file=sys.stderr)
        return 2

    # Load text from file subcommand or from remainder.
    text: str | None = None
    if remaining and remaining[0] == "add":
        addp = argparse.ArgumentParser(prog="b1e55ed signal add", add_help=False)
        addp.add_argument("--file", required=True)
        try:
            add_ns = addp.parse_args(remaining[1:])
        except SystemExit:
            print("error: usage: b1e55ed signal add --file <path>", file=sys.stderr)
            return 2

        fp = Path(str(add_ns.file))
        if not fp.exists():
            print(f"error: file not found: {fp}", file=sys.stderr)
            return 2
        text = fp.read_text(encoding="utf-8")
    else:
        # remaining is treated as free-form text (shell quoting is handled by the OS)
        text = " ".join(remaining).strip() if remaining else None

    if not text or not str(text).strip():
        print("error: signal text required", file=sys.stderr)
        return 2

    raw = str(text).strip()
    content_len = len(raw)

    # Symbols: explicit override wins, otherwise extract from content.
    syms: list[str]
    if symbols_raw:
        syms = [s.strip().upper() for s in str(symbols_raw).split(",") if s.strip()]
    else:
        syms = _extract_symbols(raw, universe=config.universe.symbols)

    if not syms:
        syms = ["GLOBAL"]

    base_source = str(source_raw or "operator")
    if ":" in base_source:
        source = base_source
    else:
        source = f"{base_source}:{identity.identity.node_id}"

    events: list[dict[str, object]] = []
    for sym in syms:
        payload_obj = CuratorSignalPayload(
            symbol=sym,
            direction=str(direction),
            conviction=float(conviction),
            rationale=raw,
            source=source,
        )
        payload = payload_obj.model_dump(mode="json")
        ev = db.append_event(
            event_type=EventType.SIGNAL_CURATOR_V1,
            payload=payload,
            source="cli.signal",
            dedupe_key=compute_dedupe_key(EventType.SIGNAL_CURATOR_V1, payload),
        )
        events.append({"id": ev.id, "type": str(ev.type), "ts": ev.ts.isoformat(), "payload": ev.payload})

    out = {
        "status": "ok",
        # Stable schema for operator tooling:
        "event_id": str(events[0]["id"]),
        "symbols": syms,
        "content_len": content_len,
        # Extended details (best-effort):
        "events": events,
    }

    if as_json:
        print(_json_dumps(out))
    else:
        print(f"signal ingested: {len(events)} event(s)")
        from typing import cast

        for ev in events:
            d = cast(dict[str, object], ev)
            ev_id = str(d.get("id", ""))
            payload = d.get("payload")
            sym = ""
            if isinstance(payload, dict):
                sym = str(payload.get("symbol", ""))
            print(f"- {ev_id} {sym}")
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
                str(p["asset"]),
                str(p["direction"]),
                f"{float(p['entry_price']):.2f}",
                f"{float(p['mark_price']):.2f}" if p["mark_price"] is not None else "-",
                f"{float(p['size_notional']):.2f}",
                f"{pnl:+.2f}" if pnl is not None else "-",
                str(p["id"])[:8],
            ]
        )

    _print_table(["asset", "dir", "entry", "mark", "notional", "pnl", "id"], table_rows)
    return 0


def _cmd_producers(ctx: CliContext, args: argparse.Namespace) -> int:
    from datetime import UTC, datetime

    from engine.core.database import Database

    def ensure_endpoint_column(db: Database) -> None:
        cols = [str(r[1]) for r in db.conn.execute("PRAGMA table_info(producer_health)").fetchall()]
        if "endpoint" in cols:
            return
        with db.conn:
            db.conn.execute("ALTER TABLE producer_health ADD COLUMN endpoint TEXT")

    repo_root = ctx.repo_root
    db = Database(repo_root / "data" / "brain.db")
    ensure_endpoint_column(db)

    cmd = str(getattr(args, "producers_cmd", "") or "")
    if not cmd:
        print("error: missing producers subcommand (register|list|remove)", file=sys.stderr)
        return 2

    if cmd == "register":
        name = str(args.name)
        domain = str(args.domain)
        endpoint = str(args.endpoint)
        schedule = str(args.schedule)

        now = datetime.now(tz=UTC).isoformat()
        existing = db.conn.execute("SELECT name FROM producer_health WHERE name = ?", (name,)).fetchone()
        if existing is not None:
            print(f"error: producer already registered: {name}", file=sys.stderr)
            return 1

        with db.conn:
            db.conn.execute(
                "INSERT INTO producer_health (name, domain, schedule, endpoint, updated_at) VALUES (?, ?, ?, ?, ?)",
                (name, domain, schedule, endpoint, now),
            )

        out_obj = {
            "status": "ok",
            "producer": {
                "name": name,
                "domain": domain,
                "endpoint": endpoint,
                "schedule": schedule,
                "registered_at": now,
            },
        }
        print(_json_dumps(out_obj))
        return 0

    if cmd == "list":
        rows = db.conn.execute("SELECT name, domain, schedule, endpoint, updated_at FROM producer_health ORDER BY name ASC").fetchall()
        out: list[dict[str, str]] = [
            {
                "name": str(r[0]),
                "domain": str(r[1] or ""),
                "schedule": str(r[2] or ""),
                "endpoint": str(r[3] or ""),
                "registered_at": str(r[4] or ""),
            }
            for r in rows
        ]

        if bool(getattr(args, "json", False)):
            print(_json_dumps(out))
            return 0

        if not out:
            print("(no registered producers)")
            return 0

        table_rows: list[list[str]] = [[p["name"], p["domain"], p["schedule"], p["endpoint"]] for p in out]
        _print_table(["name", "domain", "schedule", "endpoint"], table_rows)
        return 0

    if cmd == "remove":
        name = str(args.name)
        with db.conn:
            cur = db.conn.execute("DELETE FROM producer_health WHERE name = ?", (name,))
        if cur.rowcount == 0:
            print(f"error: producer not found: {name}", file=sys.stderr)
            return 1
        print(_json_dumps({"status": "ok", "removed": name}))
        return 0

    print(f"error: unknown producers subcommand: {cmd}", file=sys.stderr)
    return 2


def _cmd_contributors(ctx: CliContext, args: argparse.Namespace) -> int:
    from engine.core.config import Config
    from engine.core.database import Database
    from engine.core.scoring import ContributorScoring
    from engine.security.identity import ensure_identity

    repo_root = ctx.repo_root
    db = Database(repo_root / "data" / "brain.db")

    cfg_path = repo_root / "config" / "user.yaml"
    config = Config.from_yaml(cfg_path) if cfg_path.exists() else Config.from_repo_defaults(repo_root)

    cmd = str(getattr(args, "contributors_cmd", "") or "")

    reg = _build_contributor_registry_with_eas(db=db, config=config)
    scoring = ContributorScoring(db)

    if cmd == "list":
        items = reg.list_all()
        if bool(getattr(args, "json", False)):
            print(_json_dumps([c.__dict__ for c in items]))
            return 0

        rows: list[list[str]] = []
        for c in items:
            rows.append([c.id, c.node_id, c.role, c.name, c.registered_at])
        if rows:
            _print_table(["id", "node_id", "role", "name", "registered_at"], rows)
        return 0

    if cmd == "register":
        node_id = str(getattr(args, "node_id", "") or "")
        if not node_id:
            ident = ensure_identity().identity
            node_id = ident.node_id

        try:
            meta: dict[str, object] = {}
            # Pass schema_uid into metadata so ContributorRegistry can include it in the signed payload.
            if bool(getattr(args, "attest", False)) and bool(config.eas.schema_uid):
                meta["eas"] = {"schema_uid": str(config.eas.schema_uid)}

            c = reg.register(
                node_id=node_id,
                name=str(args.name),
                role=str(args.role),
                metadata=meta,
                attest=bool(getattr(args, "attest", False)),
            )
        except ValueError:
            print(f"error: contributor already exists for node_id: {node_id}", file=sys.stderr)
            return 2

        print(_json_dumps({"status": "ok", "contributor": c.__dict__}))
        return 0

    if cmd == "remove":
        cid = str(args.id)
        ok = reg.deregister(cid)
        if not ok:
            print(f"error: contributor not found: {cid}", file=sys.stderr)
            return 2
        print(_json_dumps({"status": "ok", "removed": cid}))
        return 0

    if cmd == "score":
        cid = str(args.id)
        s = scoring.compute_score(cid)
        if bool(getattr(args, "json", False)):
            print(_json_dumps(s.__dict__))
        else:
            print(f"score: {s.score:.2f} (hit_rate={s.hit_rate:.2%}, submitted={s.signals_submitted}, accepted={s.signals_accepted}, streak={s.streak})")
        return 0

    if cmd == "leaderboard":
        limit = int(getattr(args, "limit", 20) or 20)
        items = scoring.leaderboard(limit=limit)
        if bool(getattr(args, "json", False)):
            print(_json_dumps([s.__dict__ for s in items]))
            return 0

        rows = []
        for s in items:
            c = reg.get(s.contributor_id)
            rows.append(
                [
                    s.contributor_id,
                    c.name if c else "",
                    f"{s.score:.2f}",
                    f"{s.hit_rate:.2%}",
                    str(s.signals_submitted),
                    str(s.signals_accepted),
                    str(s.streak),
                ]
            )
        if rows:
            _print_table(["id", "name", "score", "hit_rate", "submitted", "accepted", "streak"], rows)
        return 0

    print("error: missing contributors subcommand (list|register|remove|score|leaderboard)", file=sys.stderr)
    return 2


def _cmd_eas(ctx: CliContext, args: argparse.Namespace) -> int:
    from engine.core.config import Config
    from engine.core.database import Database

    repo_root = ctx.repo_root
    cfg_path = repo_root / "config" / "user.yaml"
    config = Config.from_yaml(cfg_path) if cfg_path.exists() else Config.from_repo_defaults(repo_root)

    cmd = str(getattr(args, "eas_cmd", "") or "")
    if not cmd:
        print("error: missing eas subcommand (status|verify)", file=sys.stderr)
        return 2

    if cmd == "status":
        from engine.integrations.eas_schema import CONTRIBUTOR_SCHEMA, EXPECTED_SCHEMA_HASH

        pk_present = bool(str(config.eas.attester_private_key or "").strip())
        out = {
            "enabled": bool(config.eas.enabled),
            "mode": str(config.eas.mode),
            "rpc_url": str(config.eas.rpc_url),
            "eas_contract": str(config.eas.eas_contract),
            "schema_registry": str(config.eas.schema_registry),
            "schema_uid": str(config.eas.schema_uid),
            "attester_private_key_present": pk_present,
            "schema": {"string": CONTRIBUTOR_SCHEMA, "expected_hash": EXPECTED_SCHEMA_HASH},
        }

        if bool(getattr(args, "json", False)):
            print(_json_dumps(out))
        else:
            print(_json_dumps(out))
        return 0

    if cmd == "verify":
        uid = str(getattr(args, "uid", "") or "")
        if not uid:
            print("error: --uid required", file=sys.stderr)
            return 2

        # We only verify locally stored off-chain attestations (in contributor metadata).
        db = Database(repo_root / "data" / "brain.db")
        reg = _build_contributor_registry_with_eas(db=db, config=config)

        found: dict[str, object] | None = None
        for c in reg.list_all():
            eas_meta = c.metadata.get("eas") if isinstance(c.metadata, dict) else None
            if not isinstance(eas_meta, dict):
                continue
            if str(eas_meta.get("uid") or "").lower() == uid.lower():
                att = eas_meta.get("attestation")
                if isinstance(att, dict):
                    found = att
                break

        if found is None:
            out = {"ok": False, "error": "attestation.not_found", "uid": uid}
            print(_json_dumps(out))
            return 1

        ok = False
        try:
            from engine.integrations.eas import EASClient

            client = EASClient(
                rpc_url=str(config.eas.rpc_url),
                eas_address=str(config.eas.eas_contract),
                schema_registry_address=str(config.eas.schema_registry),
                private_key="",  # not required for verify
            )
            ok = bool(client.verify_offchain_attestation(found))
        except Exception as e:
            out = {"ok": False, "uid": uid, "error": str(e)}
            print(_json_dumps(out))
            return 1

        out = {"ok": ok, "uid": uid}
        if bool(getattr(args, "json", False)):
            print(_json_dumps(out))
        else:
            print(_json_dumps(out))
        return 0 if ok else 1

    print(f"error: unknown eas subcommand: {cmd}", file=sys.stderr)
    return 2


def _build_contributor_registry_with_eas(*, db: Database, config: Config) -> ContributorRegistry:
    """Construct a ContributorRegistry, optionally wired with an EAS client."""

    from engine.core.contributors import ContributorRegistry

    try:
        from engine.integrations.eas import EASClient
    except Exception:
        return ContributorRegistry(db)

    if not bool(config.eas.enabled):
        return ContributorRegistry(db)

    client = EASClient(
        rpc_url=str(config.eas.rpc_url),
        eas_address=str(config.eas.eas_contract),
        schema_registry_address=str(config.eas.schema_registry),
        private_key=str(config.eas.attester_private_key),
    )
    return ContributorRegistry(db, eas_client=client)


def _cmd_webhooks(ctx: CliContext, args: argparse.Namespace) -> int:
    from engine.core.database import Database
    from engine.core.webhooks import add_webhook_subscription, list_webhook_subscriptions, remove_webhook_subscription

    repo_root = ctx.repo_root
    db = Database(repo_root / "data" / "brain.db")

    cmd = str(getattr(args, "webhooks_cmd", "") or "")
    if cmd == "add":
        url = str(args.url)
        events = str(args.events)
        sub_id = add_webhook_subscription(db, url=url, event_globs=events, enabled=True)
        out = {"status": "ok", "id": sub_id, "url": url, "event_globs": events, "enabled": True}
        print(_json_dumps(out))
        return 0

    if cmd == "list":
        subs = list_webhook_subscriptions(db)
        if bool(getattr(args, "json", False)):
            print(_json_dumps([s.__dict__ for s in subs]))
            return 0

        rows: list[list[str]] = []
        for s in subs:
            rows.append([str(s.id), "yes" if s.enabled else "no", s.event_globs, s.url])
        if rows:
            _print_table(["id", "enabled", "events", "url"], rows)
        return 0

    if cmd == "remove":
        ok = remove_webhook_subscription(db, sub_id=int(args.id))
        if not ok:
            print(f"error: subscription not found: {args.id}", file=sys.stderr)
            return 2
        print(_json_dumps({"status": "ok", "id": int(args.id)}))
        return 0

    print("error: missing webhooks subcommand (add|list|remove)", file=sys.stderr)
    return 2


def _kill_switch_state(db) -> dict[str, object]:
    from engine.brain.kill_switch import LEVEL_MESSAGES, KillSwitchLevel
    from engine.core.events import EventType

    evs = db.get_events(event_type=EventType.KILL_SWITCH_V1, limit=1)
    if not evs:
        return {"level": 0, "reason": LEVEL_MESSAGES.get(KillSwitchLevel.SAFE, "Normal operation."), "ts": None}

    ev = evs[0]
    lvl = _safe_int(ev.payload.get("level"))
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
            "previous_level": _safe_int(prev.get("level")),
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
    from engine.core.time import parse_dt, utc_now

    repo_root = ctx.repo_root
    db = Database(repo_root / "data" / "brain.db")

    def _mk(
        *,
        alert_id: str,
        alert_type: str,
        severity: str,
        message: str,
        ts: str | None,
        meta: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return {
            "id": str(alert_id),
            "type": str(alert_type),
            "severity": str(severity),
            "message": str(message),
            "meta": dict(meta or {}),
            "ts": str(ts or ""),
        }

    cutoff = None
    if getattr(args, "since", None) is not None:
        mins = int(args.since)
        if mins < 0:
            print("error: --since must be >= 0", file=sys.stderr)
            return 2
        cutoff = utc_now() if mins == 0 else utc_now() - timedelta(minutes=mins)

    alerts: list[dict[str, object]] = []

    # Kill switch alert
    ks = _kill_switch_state(db)
    ks_level = _safe_int(ks.get("level"))
    if ks_level > 0:
        alerts.append(
            _mk(
                alert_id="kill_switch",
                alert_type="kill_switch",
                severity="CRITICAL",
                message=str(ks.get("reason") or "kill switch enabled"),
                ts=str(ks.get("ts") or ""),
                meta={"level": ks_level, "reason": ks.get("reason"), "previous_level": ks.get("previous_level")},
            )
        )

    # Producer health
    rows = db.conn.execute(
        "SELECT name, domain, consecutive_failures, last_error, last_run_at FROM producer_health WHERE consecutive_failures > 0 OR last_error IS NOT NULL"
    ).fetchall()
    for r in rows:
        name = str(r[0])
        domain = str(r[1] or "")
        failures = int(r[2] or 0)
        err = str(r[3] or "")
        ts = str(r[4] or "")
        alerts.append(
            _mk(
                alert_id=f"producer:{name}",
                alert_type="producer",
                severity="WARNING",
                message=f"{name} ({domain}): {err}".strip(),
                ts=ts,
                meta={"name": name, "domain": domain, "consecutive_failures": failures, "last_error": err},
            )
        )

    # Position stops/targets (with stop proximity)
    mark = _latest_mark_prices(db)
    pos = db.conn.execute(
        "SELECT asset, direction, stop_loss, take_profit, opened_at, id "
        "FROM positions "
        "WHERE status = 'open' AND (stop_loss IS NOT NULL OR take_profit IS NOT NULL)"
    ).fetchall()
    for r in pos:
        sym = str(r[0]).upper()
        direction = str(r[1])
        stop = float(r[2]) if r[2] is not None else None
        tp = float(r[3]) if r[3] is not None else None
        ts = str(r[4])
        pid = str(r[5])

        mp = mark.get(sym)

        sev = "INFO"
        meta: dict[str, object] = {"position_id": pid, "asset": sym, "direction": direction, "stop_loss": stop, "take_profit": tp}
        msg = f"{sym} stop={stop if stop is not None else '-'} tp={tp if tp is not None else '-'}"

        if stop is not None and mp is not None:
            # distance to stop as a fraction of stop
            dist_frac = abs(float(mp) - float(stop)) / float(stop) if float(stop) != 0 else 0.0
            meta["mark_price"] = float(mp)
            meta["stop_distance_pct"] = float(dist_frac * 100.0)

            # if already breached, always CRITICAL
            breached = (direction == "long" and float(mp) <= float(stop)) or (direction == "short" and float(mp) >= float(stop))
            if breached or dist_frac <= 0.0025:
                sev = "CRITICAL"
                msg = f"{sym} near stop ({dist_frac * 100:.2f}%): mark={float(mp):.4f} stop={float(stop):.4f}"
            elif dist_frac < 0.01:
                sev = "WARNING"
                msg = f"{sym} approaching stop ({dist_frac * 100:.2f}%): mark={float(mp):.4f} stop={float(stop):.4f}"

        alerts.append(
            _mk(
                alert_id=f"position:{pid}",
                alert_type="position",
                severity=sev,
                message=msg,
                ts=ts,
                meta=meta,
            )
        )

    # Filter + sort
    if cutoff is not None:
        filtered: list[dict[str, object]] = []
        for a in alerts:
            ts_s = str(a.get("ts") or "").strip()
            if not ts_s:
                continue
            try:
                if parse_dt(ts_s) >= cutoff:
                    filtered.append(a)
            except Exception:  # noqa: BLE001
                # If we can't parse, keep it (better than silently dropping).
                filtered.append(a)
        alerts = filtered

    sev_rank = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}

    def _sort_key(a: dict[str, object]) -> tuple[int, str]:
        return (sev_rank.get(str(a.get("severity") or "INFO"), 99), str(a.get("ts") or ""))

    alerts.sort(key=_sort_key)

    if bool(getattr(args, "json", False)):
        print(_json_dumps(alerts))
        return 0

    print("active alerts")
    if not alerts:
        print("(none)")
        return 0

    table_rows = [[str(a.get("type")), str(a.get("severity")), str(a.get("message")), str(a.get("ts") or "")] for a in alerts]
    _print_table(["type", "severity", "message", "ts"], table_rows)
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


def _cmd_identity(ctx: CliContext, args: argparse.Namespace) -> int:
    action = getattr(args, "identity_action", None)
    if action == "forge":
        return _identity_forge(ctx, args)
    if action == "show":
        return _identity_show(ctx, args)

    print("error: missing identity subcommand (forge/show)", file=sys.stderr)
    return 2


def _format_elapsed(seconds: float) -> str:
    s = int(seconds)
    m, s = divmod(s, 60)
    if m <= 0:
        return f"{s}s"
    return f"{m}m {s}s"


def _identity_show(ctx: CliContext, args: argparse.Namespace) -> int:
    use_json = bool(getattr(args, "json", False))

    identity_path = ctx.repo_root / ".b1e55ed" / "identity.json"
    if not identity_path.exists():
        if use_json:
            print(_json_dumps({"ok": False, "error": "identity_not_found"}))
        else:
            print("No forged identity found. Run: b1e55ed identity forge")
        return 1

    try:
        data = json.loads(identity_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        if use_json:
            print(_json_dumps({"ok": False, "error": "identity_unreadable"}))
        else:
            print(f"Identity file unreadable: {identity_path}")
        return 1

    if use_json:
        out = {"ok": True, "identity": data}
        print(_json_dumps(out))
        return 0

    print("forged identity")
    print(f"- address: {data.get('address', '')}")
    print(f"- node_id: {data.get('node_id', '')}")
    print(f"- forged_at: {data.get('forged_at', '')}")
    print(f"- candidates_evaluated: {data.get('candidates_evaluated', '')}")
    return 0


def _identity_forge(ctx: CliContext, args: argparse.Namespace) -> int:
    """The Forge — identity derivation ritual."""

    import shutil
    import subprocess
    import time

    use_json = bool(getattr(args, "json", False))
    threads = int(getattr(args, "threads", None) or (os.cpu_count() or 4))
    prefix = "b1e55ed"

    # Expected candidates for 7 hex chars
    expected = 16 ** len(prefix)

    if not use_json:
        print()
        print("  ╔══════════════════════════════════════╗")
        print("  ║         THE FORGE                    ║")
        print("  ║         b1e55ed identity protocol    ║")
        print("  ╚══════════════════════════════════════╝")
        print()
        print(f"  Every address in this network begins with 0x{prefix}.")
        print("  Yours is being derived now.")
        print()
        print("  This takes a few minutes.")
        print("  The work is the point.")
        print()
        print("  Searching...")
        print()

    rust_binary = shutil.which("b1e55ed-forge")
    if rust_binary is None:
        repo_binary = ctx.repo_root / "tools" / "forge" / "target" / "release" / "b1e55ed-forge"
        if repo_binary.exists():
            rust_binary = str(repo_binary)

    result: dict[str, object] | None = None

    def _render_progress(msg: dict[str, object]) -> None:
        candidates = _safe_int(msg.get("candidates"))
        elapsed_ms = _safe_int(msg.get("elapsed_ms"))
        pct = min((candidates / expected) * 100.0 if expected else 0.0, 99.9)
        bar_width = 24
        filled = int(bar_width * pct / 100.0)
        bar = "▓" * filled + "░" * (bar_width - filled)
        elapsed = _format_elapsed(elapsed_ms / 1000.0)
        print(
            f"\r  {bar}  {pct:5.1f}%\n  {candidates:,} candidates evaluated\n  Elapsed: {elapsed}",
            end="\033[F\033[F",
            flush=True,
        )

    if rust_binary:
        proc = subprocess.Popen(
            [rust_binary, "--prefix", prefix, "--threads", str(threads), "--json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            if msg.get("type") == "progress" and use_json:
                print(_json_dumps(msg))
            elif msg.get("type") == "progress" and not use_json:
                _render_progress(msg)
            elif msg.get("type") == "found":
                result = msg
                break
        proc.wait()
    else:
        if not use_json:
            print("  (Rust grinder not found — using Python fallback. This will be slower.)")
            print()

        from engine.integrations.forge import grind

        for msg in grind(prefix):
            if msg.get("type") == "progress" and use_json:
                print(_json_dumps(msg))
            elif msg.get("type") == "progress" and not use_json:
                _render_progress(msg)
            elif msg.get("type") == "found":
                result = msg
                break

    if result is None:
        print("\n  Forge failed. No address found.")
        return 1

    address = str(result.get("address") or "")
    private_key = str(result.get("private_key") or "")
    candidates = _safe_int(result.get("candidates"))
    elapsed_ms = _safe_int(result.get("elapsed_ms"))

    identity_dir = ctx.repo_root / ".b1e55ed"
    identity_dir.mkdir(exist_ok=True)

    identity_data = {
        "address": address,
        "node_id": f"eth:{address.lower()}",
        "forged_at": int(time.time()),
        "candidates_evaluated": candidates,
        "elapsed_ms": elapsed_ms,
    }

    identity_path = identity_dir / "identity.json"
    identity_path.write_text(json.dumps(identity_data, indent=2), encoding="utf-8")

    key_path = identity_dir / "forge_key.enc"
    key_path.write_text(private_key, encoding="utf-8")
    key_path.chmod(0o600)

    attestation_uid = None
    try:
        config = _load_config(ctx)
        if config and bool(config.eas.enabled):
            from engine.integrations.eas import AttestationData, EASClient

            eas = EASClient(
                rpc_url=config.eas.rpc_url,
                eas_address=config.eas.eas_contract,
                schema_registry_address=config.eas.schema_registry,
                private_key=config.eas.attester_private_key,
            )
            att = eas.create_offchain_attestation(
                AttestationData(
                    schema_uid=config.eas.schema_uid,
                    recipient=address,
                    data={
                        "nodeId": identity_data["node_id"],
                        "name": "",
                        "role": "operator",
                        "version": "1.0.0-beta.2",
                        "registeredAt": identity_data["forged_at"],
                    },
                )
            )
            if att:
                attestation_uid = str(att.get("uid") or "pending")
    except Exception:  # noqa: BLE001
        attestation_uid = None

    if use_json:
        out = {**identity_data, "attestation_uid": attestation_uid}
        print(_json_dumps(out))
        return 0

    print("\n\n")
    print("  ──────────────────────────────────────")
    print()
    print("  Forged.")
    print()
    print(f"  Address:   {address}")
    print(f"  Node:      {identity_data['node_id']}")
    if attestation_uid:
        print(f"  Attested:  EAS #{attestation_uid[:10]}... (Ethereum)")
    print()
    print(f"  {candidates:,} candidates evaluated in {elapsed_ms / 1000:.1f}s")
    print()
    print(f"  Your key is stored at {key_path}")
    print("  There is no recovery. Guard it accordingly.")
    print()
    print("  Welcome to the upper class.")
    print()
    print("  ──────────────────────────────────────")
    print()
    return 0


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


def _cmd_replay(ctx: CliContext, args: argparse.Namespace) -> int:
    """Rebuild all projections from event replay."""
    import time

    from engine.core.database import Database
    from engine.core.projections import ProjectionManager

    repo_root = ctx.repo_root
    db = Database(repo_root / "data" / "brain.db")

    try:
        t0 = time.monotonic()
        events = db.iter_events_ascending(
            from_id=getattr(args, "from_id", None),
            to_id=getattr(args, "to_id", None),
        )
        pm = ProjectionManager()
        pm.rebuild(events)
        elapsed = time.monotonic() - t0
        state: dict[str, Any] = pm.get_state()

        result = {
            "status": "ok",
            "events_replayed": len(events),
            "elapsed_seconds": round(elapsed, 3),
            "projections": {k: len(v) if isinstance(v, dict) else v for k, v in state.items()},
        }

        if getattr(args, "json", False):
            print(_json_dumps(result))
        else:
            print(f"Replayed {len(events)} events in {elapsed:.3f}s")
            projections = cast(dict[str, object], result["projections"])
            for name, val in projections.items():
                print(f"  {name}: {val} entries")
            print("Projections rebuilt successfully.")
    finally:
        db.close()
    return 0


def _cmd_integrity(ctx: CliContext, args: argparse.Namespace) -> int:
    """Verify event chain integrity and projection determinism."""
    import time

    from engine.core.database import Database
    from engine.core.projections import ProjectionManager

    repo_root = ctx.repo_root
    db = Database(repo_root / "data" / "brain.db")

    try:
        t0 = time.monotonic()
        checks: dict[str, object] = {}

        # 1. Hash chain verification
        fast = getattr(args, "fast", False)
        chain_ok = db.verify_hash_chain(fast=fast)
        checks["hash_chain"] = "pass" if chain_ok else "FAIL"

        # 2. Concurrent writer detection
        concurrent = db.detect_concurrent_writers()
        checks["single_writer"] = "FAIL (concurrent writer detected)" if concurrent else "pass"

        # 3. Projection determinism: replay twice, compare
        events = db.iter_events_ascending()
        pm1 = ProjectionManager()
        pm1.rebuild(events)
        state1 = pm1.get_state()

        pm2 = ProjectionManager()
        pm2.rebuild(events)
        state2 = pm2.get_state()

        deterministic = _json_dumps(state1) == _json_dumps(state2)
        checks["projection_determinism"] = "pass" if deterministic else "FAIL"

        # 4. Event count
        checks["event_count"] = len(events)

        elapsed = time.monotonic() - t0
        all_pass = all(v == "pass" for k, v in checks.items() if k != "event_count")

        result = {
            "status": "ok" if all_pass else "FAIL",
            "checks": checks,
            "elapsed_seconds": round(elapsed, 3),
        }

        if getattr(args, "json", False):
            print(_json_dumps(result))
        else:
            print(f"Integrity check ({'PASS' if all_pass else 'FAIL'}):")
            for name, val in checks.items():
                icon = "✅" if val == "pass" or isinstance(val, int) else "❌"
                print(f"  {icon} {name}: {val}")
            print(f"  Completed in {elapsed:.3f}s")
        return 0 if all_pass else 1
    finally:
        db.close()


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

    # Commands that don't require forged identity
    ungated_commands = {"identity", "setup"}

    cmd = getattr(args, "command", None)
    if cmd not in ungated_commands:
        from engine.core.identity_gate import is_dev_mode, load_identity

        if not is_dev_mode() and load_identity(ctx.repo_root) is None:
            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {
                            "error": {
                                "code": "IDENTITY_REQUIRED",
                                "message": "Identity required. Run `b1e55ed identity forge` first.",
                            }
                        }
                    )
                )
            else:
                print()
                print("  Identity required.")
                print()
                print("  Every participant in the b1e55ed network must forge an identity.")
                print("  This is a one-time process that derives your unique 0xb1e55ed address.")
                print()
                print("  Run:  b1e55ed identity forge")
                print()
            return 1

    dispatch: dict[str, Callable[[CliContext, argparse.Namespace], int]] = {
        "setup": _cmd_setup,
        "brain": _cmd_brain,
        "signal": _cmd_signal,
        "alerts": _cmd_alerts,
        "positions": _cmd_positions,
        "producers": _cmd_producers,
        "contributors": _cmd_contributors,
        "eas": _cmd_eas,
        "webhooks": _cmd_webhooks,
        "kill-switch": _cmd_kill_switch,
        "health": _cmd_health,
        "keys": _cmd_keys,
        "identity": _cmd_identity,
        "api": _cmd_api,
        "dashboard": _cmd_dashboard,
        "status": _cmd_status,
        "replay": _cmd_replay,
        "integrity": _cmd_integrity,
    }

    fn = dispatch.get(str(args.command))
    if fn is None:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 2

    return int(fn(ctx, args))


if __name__ == "__main__":
    raise SystemExit(main())
