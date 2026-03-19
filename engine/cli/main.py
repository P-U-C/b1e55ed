"""engine.cli

Command line interface entry point for b1e55ed.

Design constraints:
- argparse-based.
- Lazy imports: do not import heavy dependencies at parse time.

The hex is blessed: 0xb1e55ed.
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import json
import os
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from engine.core.paths import b1e55ed_dir, get_db_path

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
    """Return operator data root.

    For dev checkouts (pyproject.toml present in cwd or any parent up to
    5 levels), returns the repo root so config/default.yaml is found
    relative to source.

    For production uv tool installs, returns ~/.b1e55ed/ so all operator
    data (config/, data/, corpus/) lives under the standard dir.
    """
    candidate = Path.cwd()
    for _ in range(5):
        if (candidate / "pyproject.toml").exists():
            return candidate
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return b1e55ed_dir()

    # Droste effect eliminated — one level of nesting is enough for anyone


def _identity_dir(ctx: CliContext) -> Path:
    """Return the directory where identity files are stored.

    Always ~/.b1e55ed/ — identity is user-scoped regardless of dev vs production.
    In dev checkouts, repo_root is the repo dir (no .b1e55ed suffix).
    In production, repo_root IS ~/.b1e55ed, so we must not append .b1e55ed again.
    """
    return Path.home() / ".b1e55ed"


def _resolve_db_path(repo_root: Path, config: object | None = None) -> Path:
    """Derive brain.db path — delegates to get_db_path() (single source of truth)."""
    return get_db_path(config)


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

    from engine.cli.commands.setup import build_setup_parser as _build_setup_parser

    _build_setup_parser(sub)

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
    p_brain.add_argument(
        "--force",
        action="store_true",
        help="Run even if daemon is already running (override concurrent cycle warning).",
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
    pos_sub = p_positions.add_subparsers(dest="positions_cmd")
    p_pos_close = pos_sub.add_parser("close", help="Manually close an open position")
    p_pos_close.add_argument("position_id", help="Position ID to close")
    p_pos_close.add_argument(
        "--exit-price",
        type=float,
        default=None,
        dest="exit_price",
        help="Exit price (defaults to current market price).",
    )

    # -- kelly --
    p_kelly = sub.add_parser("kelly", help="Show dynamic Kelly criterion estimate from trade history")
    p_kelly.add_argument("--asset", default=None, help="Filter by asset (e.g. BTC)")
    p_kelly.add_argument("--lookback", type=int, default=50, help="Max trades to consider")
    p_kelly.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    # -- backtest --
    p_backtest = sub.add_parser("backtest", help="Run backtests (walk-forward + stats)")
    bt_sub = p_backtest.add_subparsers(dest="backtest_cmd")

    p_bt_wf = bt_sub.add_parser("walkforward", help="Walk-forward backtest")
    p_bt_wf.add_argument(
        "--strategy",
        required=True,
        choices=[
            "momentum",
            "ma_crossover",
            "rsi_reversion",
            "breakout",
            "mean_reversion",
            "trend_following",
            "volatility",
            "combined",
        ],
    )
    p_bt_wf.add_argument("--prices", required=True, help="Path to CSV with columns: close[,high,low,volume]")
    p_bt_wf.add_argument("--train", type=int, default=180, help="Train window size (bars)")
    p_bt_wf.add_argument("--test", type=int, default=60, help="Test window size (bars)")
    p_bt_wf.add_argument("--step", type=int, default=60, help="Step size (bars)")
    p_bt_wf.add_argument("--embargo", type=int, default=0, help="Embargo gap between train/test (bars)")
    p_bt_wf.add_argument("--fee-bps", type=float, default=10.0, help="Fee per position change (bps)")
    p_bt_wf.add_argument("--q", type=float, default=0.05, help="FDR q-value")
    p_bt_wf.add_argument("--bootstrap", type=int, default=2000, help="Bootstrap samples")
    p_bt_wf.add_argument("--seed", type=int, default=0, help="RNG seed")
    p_bt_wf.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    # -- backtest gridsweep --
    p_bt_gs = bt_sub.add_parser("gridsweep", help="Parameter grid sweep with FDR correction across all combos")
    p_bt_gs.add_argument(
        "--strategy",
        required=True,
        choices=[
            "momentum",
            "ma_crossover",
            "rsi_reversion",
            "breakout",
            "mean_reversion",
            "trend_following",
            "volatility",
            "combined",
        ],
    )
    p_bt_gs.add_argument("--prices", required=True, help="Path to CSV with columns: close[,high,low,volume]")
    p_bt_gs.add_argument(
        "--param",
        action="append",
        dest="params",
        default=[],
        metavar="NAME=v1,v2,...",
        help="Parameter sweep specification (repeatable). E.g. --param lookback=10,20,30",
    )
    p_bt_gs.add_argument("--train", type=int, default=180, help="Train window size (bars)")
    p_bt_gs.add_argument("--test", type=int, default=60, help="Test window size (bars)")
    p_bt_gs.add_argument("--step", type=int, default=60, help="Step size (bars)")
    p_bt_gs.add_argument("--embargo", type=int, default=0, help="Embargo gap between train/test (bars)")
    p_bt_gs.add_argument("--fee-bps", type=float, default=10.0, help="Fee per position change (bps)")
    p_bt_gs.add_argument("--q", type=float, default=0.05, help="FDR q-value")
    p_bt_gs.add_argument("--bootstrap", type=int, default=2000, help="Bootstrap samples")
    p_bt_gs.add_argument("--seed", type=int, default=0, help="RNG seed")
    p_bt_gs.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    # -- backtest megasweep --
    p_bt_ms = bt_sub.add_parser("megasweep", help="Multi-strategy parameter sweep with FDR across ALL strategies × ALL combos")
    p_bt_ms.add_argument("--prices", required=True, help="Path to CSV with columns: close[,high,low,volume]")
    p_bt_ms.add_argument(
        "--grid",
        action="append",
        dest="grids",
        default=[],
        metavar="STRATEGY:p1=v1,v2;p2=v3,v4",
        help="Strategy grid spec (repeatable). E.g. --grid 'momentum:lookback=10,20;threshold=0.01,0.02'. Omit to use --all-defaults.",
    )
    p_bt_ms.add_argument(
        "--all-defaults",
        action="store_true",
        help="Run all 8 strategies with predefined parameter grids.",
    )
    p_bt_ms.add_argument("--train", type=int, default=180, help="Train window size (bars)")
    p_bt_ms.add_argument("--test", type=int, default=60, help="Test window size (bars)")
    p_bt_ms.add_argument("--step", type=int, default=60, help="Step size (bars)")
    p_bt_ms.add_argument("--embargo", type=int, default=0, help="Embargo gap between train/test (bars)")
    p_bt_ms.add_argument("--fee-bps", type=float, default=10.0, help="Fee per position change (bps)")
    p_bt_ms.add_argument("--q", type=float, default=0.05, help="FDR q-value")
    p_bt_ms.add_argument("--bootstrap", type=int, default=2000, help="Bootstrap samples")
    p_bt_ms.add_argument("--seed", type=int, default=0, help="RNG seed")
    p_bt_ms.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    # -- backtest regime --
    p_bt_rg = bt_sub.add_parser("regime", help="Regime-conditioned backtest — per-regime performance + FDR")
    p_bt_rg.add_argument(
        "--strategy",
        required=True,
        choices=[
            "momentum",
            "ma_crossover",
            "rsi_reversion",
            "breakout",
            "mean_reversion",
            "trend_following",
            "volatility",
            "combined",
        ],
    )
    p_bt_rg.add_argument("--prices", required=True, help="CSV with columns: close[,high,low,volume]")
    p_bt_rg.add_argument("--fee-bps", type=float, default=10.0, help="Fee per position change (bps)")
    p_bt_rg.add_argument("--q", type=float, default=0.05, help="FDR q-value")
    p_bt_rg.add_argument("--bootstrap", type=int, default=2000, help="Bootstrap samples")
    p_bt_rg.add_argument("--seed", type=int, default=0, help="RNG seed")
    p_bt_rg.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

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

    p_resolve = sub.add_parser("resolve-outcomes", help="Resolve elapsed FORECAST_V1 events into FORECAST_OUTCOME_V1")
    p_resolve.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    p_resolve_spi = sub.add_parser("resolve-spi", help="Resolve expired SPI signals against market outcomes")
    p_resolve_spi.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    # -- monitor-positions --
    p_mon = sub.add_parser(
        "monitor-positions",
        help="Evaluate stop-loss, take-profit and time-based stops for all open positions.",
    )
    p_mon.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

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

    restore_parser = identity_sub.add_parser(
        "restore",
        help="Restore identity from Ethereum private key (re-derives Ed25519 via HKDF)",
    )
    restore_parser.add_argument(
        "--eth-key",
        required=True,
        help="Ethereum private key hex (from forge_key.enc or backup)",
    )
    restore_parser.add_argument("--json", action="store_true")

    p_api = sub.add_parser("api", help="Start FastAPI server")
    p_api.add_argument("--host", default=None)
    p_api.add_argument("--port", type=int, default=None)

    p_dash = sub.add_parser("dashboard", help="Start dashboard server")
    p_dash.add_argument("--host", default=None)
    p_dash.add_argument("--port", type=int, default=None)

    p_start = sub.add_parser("start", help="Start API + dashboard together (recommended entry point)")
    p_start.add_argument("--api-port", type=int, default=5050, help="API port (default: 5050)")
    p_start.add_argument("--dashboard-port", type=int, default=5051, help="Dashboard port (default: 5051)")
    p_start.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p_start.add_argument("--no-browser", action="store_true", help="Don't open browser automatically")

    p_daemon = sub.add_parser(
        "daemon",
        help="Start all subsystems as a supervised process group (recommended for production)",
    )
    p_daemon.add_argument("--status", action="store_true", help="Show daemon status and exit")

    p_eas = sub.add_parser("eas", help="Ethereum Attestation Service (EAS) utilities")
    eas_sub = p_eas.add_subparsers(dest="eas_cmd")

    p_eas_status = eas_sub.add_parser("status", help="Show EAS config and schema status")
    p_eas_status.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    p_eas_verify = eas_sub.add_parser("verify", help="Verify an off-chain attestation by UID")
    p_eas_verify.add_argument("--uid", required=True, help="Attestation UID")
    p_eas_verify.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    # -- doctor --
    from engine.cli.doctor import build_doctor_parser

    build_doctor_parser(sub)

    sub.add_parser("status", help="Print system status")

    p_register = sub.add_parser("register", help="Register this node on-chain (ERC-8004)")
    p_register.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    sub.add_parser("wizard", help="Interactive setup wizard for new contributors")

    # -- spi --
    p_spi = sub.add_parser("spi", help="SPI signal producer management")
    spi_sub = p_spi.add_subparsers(dest="spi_cmd")

    spi_sub.add_parser("register", help="Interactively register a new SPI signal producer")
    spi_sub.add_parser("status", help="Show all registered SPI producers and lifecycle states")

    p_spi_promote = spi_sub.add_parser("promote", help="Manually promote a producer to the next lifecycle state")
    p_spi_promote.add_argument("producer_id", help="Producer ID to promote")

    p_spi_test_key = spi_sub.add_parser("test-key", help="Test that an API key is valid")
    p_spi_test_key.add_argument("producer_id", help="Producer ID whose key to test")

    p_spi.add_argument("--api-url", default="http://127.0.0.1:5050", help="API base URL (default: http://127.0.0.1:5050)")

    p_uninstall = sub.add_parser("uninstall", help="Uninstall b1e55ed and clean up all related files")
    p_uninstall.add_argument(
        "--yes",
        action="store_true",
        help="Skip all confirmations and remove everything automatically.",
    )
    p_uninstall.add_argument(
        "--keep-data",
        action="store_true",
        dest="keep_data",
        help="Remove binary/tool but preserve data and config directories.",
    )

    # -- anchor --
    from engine.cli.commands.anchor import build_anchor_parser

    build_anchor_parser(sub)

    # -- export --
    from engine.cli.commands.export import build_export_parser

    build_export_parser(sub)

    # -- report --
    from engine.cli.commands.report import build_report_parser

    build_report_parser(sub)

    # -- prune --
    p_prune = sub.add_parser("prune", help="Prune old data according to retention policy")
    p_prune.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting.",
    )
    p_prune.add_argument(
        "--events-days",
        type=int,
        default=None,
        help="Override events retention days (default: from config).",
    )
    p_prune.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )

    # -- replay --
    p_replay = sub.add_parser("replay", help="Rebuild projections from event replay")
    p_replay.add_argument("--from", dest="from_id", help="Start from event ID (inclusive)")
    p_replay.add_argument("--to", dest="to_id", help="End at event ID (inclusive)")
    p_replay.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    # -- integrity --
    p_integrity = sub.add_parser("integrity", help="Verify event chain integrity and projection consistency")
    p_integrity.add_argument("--fast", action="store_true", help="Check only recent events")
    p_integrity.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    # -- verify-chain --
    p_verify_chain = sub.add_parser("verify-chain", help="Verify the full event hash chain (alias for integrity --no-fast)")
    p_verify_chain.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    # -- reconcile --
    p_reconcile = sub.add_parser("reconcile", help="Backfill missing execution provenance events. Safe to run multiple times.")
    p_reconcile.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

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
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _ = Database(db_path)

    print("\nStatus summary")
    print(f"- repo_root: {repo_root}")
    print(f"- config: {user_cfg_path}")
    print(f"- identity: {identity.path}")
    print(f"- keystore: {keystore.describe()}")
    print(f"- db: {db_path}")

    # Optional: SPI producer registration
    if not non_interactive:
        spi_ans = input("\nWould you like to register an SPI signal producer? [y/N]: ").strip().lower()
        if spi_ans in {"y", "yes"}:
            spi_api_url = os.getenv("B1E55ED_API_URL", "http://127.0.0.1:5050")
            _spi_register_flow(spi_api_url)

    print("\nYou're blessed. Run `b1e55ed brain` to start.")
    return 0


def _cmd_brain(ctx: CliContext, args: argparse.Namespace) -> int:
    # Fix 5: Warn if daemon is already running (brain cycles are automatic when daemon is active)
    force = bool(getattr(args, "force", False))
    if not force:
        _daemon_running = False
        try:
            import psutil  # type: ignore[import-not-found,import-untyped,unused-ignore]

            for _proc in psutil.process_iter(["pid", "cmdline"]):
                _cmdline = " ".join(_proc.info.get("cmdline") or [])
                if "b1e55ed" in _cmdline and "daemon" in _cmdline:
                    _daemon_running = True
                    break
        except Exception:
            # psutil unavailable or access denied — fall back to lock-file check
            _lock_path = Path.home() / ".b1e55ed" / "daemon.lock"
            _daemon_running = _lock_path.exists()

        if _daemon_running:
            print(
                "⚠ Daemon is already running — brain cycles are automatic. Use --force to run manually.",
                file=sys.stderr,
            )
            return 0

    # Lazy import: brain pipeline can be heavy.
    from engine.core.config import Config
    from engine.core.database import Database
    from engine.security.identity import ensure_identity

    repo_root = ctx.repo_root
    cfg_path = repo_root / "config" / "user.yaml"
    config = Config.from_yaml(cfg_path) if cfg_path.exists() else Config.from_repo_defaults(repo_root)

    db = Database(_resolve_db_path(repo_root, config))
    identity = ensure_identity()

    # Best-effort crash-recovery sweep on startup.
    try:
        from engine.execution.recovery import recover_missing_karma_intents as _recover_karma

        _n = _recover_karma(db=db, config=config, identity=identity.identity)
        if _n > 0:
            import logging as _rlog

            _rlog.getLogger("b1e55ed.brain").info("Recovered %d missing karma intents", _n)
    except Exception:
        pass

    try:
        # Optional: run producers prior to orchestration.
        import logging
        from dataclasses import asdict

        from engine.core.client import DataClient
        from engine.core.metrics import REGISTRY
        from engine.core.types import ProducerHealth
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

        def _schedule_interval_ms(schedule: str) -> int | None:
            # Handles "*/N * * * *" only (good enough for health estimation)
            s = str(schedule).strip()
            if s.startswith("*/"):
                try:
                    n = int(s.split()[0][2:])
                    return int(n * 60_000)
                except Exception:
                    return None
            return None

        from datetime import datetime, timedelta

        try:
            from datetime import UTC  # py311+
        except ImportError:  # pragma: no cover
            from datetime import timezone as _tz  # noqa: PLC0415

            UTC = _tz.utc  # noqa: N806, UP017

        def _parse_iso(ts: str | None) -> datetime | None:
            if not ts:
                return None
            s = str(ts)
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            try:
                return datetime.fromisoformat(s)
            except Exception:
                return None

        def _is_quarantined(name: str) -> tuple[bool, str | None]:
            row = db.fetchone(
                "SELECT quarantined_until, quarantined_reason FROM producer_health WHERE name = ?",
                (name,),
            )
            if row is None:
                return False, None
            until = str(row[0]) if row[0] is not None else None
            reason = str(row[1]) if row[1] is not None else None
            dt = _parse_iso(until)
            if dt is None:
                return False, None
            return dt > datetime.now(tz=UTC), reason

        for n in names:
            from typing import cast

            quarantined, q_reason = _is_quarantined(n)
            if quarantined:
                producer_results.append(
                    {
                        "name": n,
                        "events_published": 0,
                        "errors": [f"quarantined:{q_reason or 'unknown'}"],
                        "duration_ms": 0,
                        "timestamp": datetime.now(tz=UTC).isoformat(),
                        "staleness_ms": None,
                        "health": "quarantined",
                    }
                )
                continue

            cls = get_producer(n)
            producer_cls = cast(type[BaseProducer], cls)
            producer = producer_cls(pctx)
            res = producer.run()

            # Persist producer health (PH1)
            domain = str(getattr(producer_cls, "domain", "") or "")
            schedule = str(getattr(producer_cls, "schedule", "") or "")
            expected_interval_ms = _schedule_interval_ms(schedule)
            last_error = "; ".join(list(res.errors)) if res.errors else None
            success = str(res.health) == str(ProducerHealth.OK)

            # Update row (create if missing)
            with db._lock, db.conn:
                db.execute(
                    """
                    INSERT INTO producer_health (
                        name, domain, schedule, endpoint, last_run_at, last_success_at, last_error,
                        consecutive_failures, events_produced, avg_duration_ms, expected_interval_ms,
                        quarantined_until, quarantined_reason, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, datetime('now'))
                    ON CONFLICT(name) DO UPDATE SET
                        domain=excluded.domain,
                        schedule=excluded.schedule,
                        last_run_at=excluded.last_run_at,
                        last_success_at=CASE WHEN ? THEN excluded.last_success_at ELSE producer_health.last_success_at END,
                        last_error=excluded.last_error,
                        consecutive_failures=CASE WHEN ? THEN 0 ELSE producer_health.consecutive_failures + 1 END,
                        events_produced=producer_health.events_produced + excluded.events_produced,
                        avg_duration_ms=CASE
                            WHEN producer_health.avg_duration_ms IS NULL THEN excluded.avg_duration_ms
                            ELSE (producer_health.avg_duration_ms * 0.8 + excluded.avg_duration_ms * 0.2)
                        END,
                        expected_interval_ms=excluded.expected_interval_ms,
                        updated_at=datetime('now')
                    """,
                    (
                        n,
                        domain,
                        schedule,
                        None,
                        res.timestamp.isoformat(),
                        res.timestamp.isoformat(),
                        last_error,
                        0 if success else 1,
                        int(res.events_published),
                        float(res.duration_ms),
                        expected_interval_ms,
                        1 if success else 0,
                        1 if success else 0,
                    ),
                )

                # Auto-quarantine after repeated failures (PH1b)
                row = db.fetchone(
                    "SELECT consecutive_failures FROM producer_health WHERE name = ?",
                    (n,),
                )
                failures = int(row[0] or 0) if row else 0
                if not success and failures >= 5:
                    until = datetime.now(tz=UTC) + timedelta(hours=1)
                    db.execute(
                        "UPDATE producer_health SET quarantined_until = ?, quarantined_reason = ? WHERE name = ?",
                        (until.isoformat(), "consecutive_failures", n),
                    )
                    db.execute(
                        "INSERT INTO audit_log (action, actor, details, ts) VALUES (?, ?, ?, datetime('now'))",
                        (
                            "producer.quarantined",
                            "system",
                            f"{n} quarantined for consecutive_failures",
                        ),
                    )

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

        ks = _kill_switch_state(db)
        if _safe_int(ks.get("level")) > 0:
            print(
                f"error: brain cycle blocked — kill switch level {ks['level']} active: {ks.get('reason', '')}",
                file=sys.stderr,
            )
            db.close()
            return 1

        orchestrator = BrainOrchestrator(config=config, db=db, identity=identity.identity)

        # Inject OMS for auto-paper-trade when execution mode is paper.
        try:
            if getattr(config.execution, "mode", "paper") == "paper":
                from engine.brain.kill_switch import KillSwitch
                from engine.execution.oms import OMS, default_sizer_from_config
                from engine.execution.preflight import Preflight, default_policy_from_risk

                policy = default_policy_from_risk(
                    max_daily_loss_usd=float(config.risk.daily_loss_limit_pct) * float(config.risk.portfolio_value_usd),
                    max_position_size_pct=float(config.risk.max_position_pct),
                    max_leverage_default=float(config.risk.max_leverage),
                )
                preflight = Preflight(policy=policy, kill_switch=KillSwitch(config=config, db=db))
                orchestrator._oms = OMS(
                    config=config,
                    db=db,
                    preflight=preflight,
                    sizer=default_sizer_from_config(config),
                    policy=policy,
                )
        except Exception:
            logging.getLogger("b1e55ed.cli").debug("OMS injection skipped", exc_info=True)

        result = orchestrator.run_cycle(symbols=config.universe.active_symbols())

        if bool(args.json):
            payload = {"cycle": asdict(result), "producers": producer_results}
            print(_json_dumps(payload))
        else:
            # The brain exhales 50KB of conviction tensors.
            # The operator needs eight lines and a checkmark.
            # --- #303: Human-readable brain cycle summary ---
            _ts = result.ts.strftime("%Y-%m-%dT%H:%M:%SZ") if result.ts else "unknown"
            _cid = result.cycle_id[:8] if result.cycle_id else "unknown"
            _regime = result.regime.state.regime if result.regime and result.regime.state else "unknown"
            _dq = result.data_quality.overall_quality * 100 if result.data_quality else 0.0

            # Find top conviction call
            _top_call = "none"
            if result.convictions:
                top_sym = max(
                    result.convictions,
                    key=lambda s: abs(result.convictions[s].final_conviction),
                )
                tc = result.convictions[top_sym]
                _dir = tc.score.direction if tc.score else "neutral"
                _mag = f"{tc.score.magnitude:.1f}" if tc.score else "?"
                _conf = f"{(tc.score.confidence or 0):.1f}" if tc.score else "?"
                _top_call = f"{top_sym} {_dir} (magnitude {_mag}, confidence {_conf})"

            # Count active domains from data quality
            _domains_active = "unknown"
            if result.data_quality:
                dq = result.data_quality
                active = [d for d, q in dq.per_domain_quality.items() if q > 0]
                total = len(dq.per_domain_quality) + len(dq.missing_domains)
                _domains_active = f"{', '.join(active) or 'none'} ({len(active)} of {total})"

            print("\n  \u2713 Brain cycle complete")
            print(f"    Cycle ID:       {_cid}")
            print(f"    Timestamp:      {_ts}")
            print(f"    Regime:         {_regime}")
            print(f"    Top call:       {_top_call}")
            print(f"    Assets scored:  {len(result.synthesis)}")
            print(f"    Data quality:   {_dq:.1f}%")
            print(f"    Domains active: {_domains_active}")
            print()

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

    db = Database(_resolve_db_path(repo_root))
    identity = ensure_identity()

    # Look up contributor for signal attribution (fail-open).
    try:
        from engine.core.contributors import ContributorRegistry

        _contrib_reg = ContributorRegistry(db)
        _contributor = _contrib_reg.get_by_node(identity.identity.node_id)
        contributor_id = _contributor.id if _contributor is not None else None
    except Exception:
        import logging as _logging

        _logging.getLogger("b1e55ed.cli").warning("Could not look up contributor for signal attribution; signal will still be emitted.")
        contributor_id = None

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
        if contributor_id is not None:
            with db._lock, db.conn:
                db.execute(
                    """
                    INSERT OR IGNORE INTO contributor_signals (contributor_id, event_id, accepted)
                    VALUES (?, ?, 0)
                    """,
                    (str(contributor_id), str(ev.id)),
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


def _cmd_kelly(ctx: CliContext, args: argparse.Namespace) -> int:
    from engine.core.database import Database
    from engine.execution.dynamic_kelly import DynamicKelly, DynamicKellyConfig

    repo_root = ctx.repo_root
    db_path = _resolve_db_path(repo_root)
    if not db_path.exists():
        print(f"error: {db_path} not found. Run `b1e55ed setup` first.", file=sys.stderr)
        return 1

    db = Database(str(db_path))
    config = DynamicKellyConfig(lookback=int(getattr(args, "lookback", 50)))
    dk = DynamicKelly(db, config=config)

    asset = getattr(args, "asset", None)
    est = dk.estimate(asset=asset)

    if bool(getattr(args, "json", False)):
        out = {
            "p": est.p,
            "b": est.b,
            "n_trades": est.n_trades,
            "n_wins": est.n_wins,
            "n_losses": est.n_losses,
            "avg_win_usd": est.avg_win_usd,
            "avg_loss_usd": est.avg_loss_usd,
            "used_prior": est.used_prior,
            "kelly_fraction": est.kelly_fraction,
            "half_kelly": est.kelly_fraction * est.params.fraction_multiplier,
        }
        print(_json_dumps(out))
    else:
        print(f"\nDynamic Kelly Estimate{f' ({asset.upper()})' if asset else ''}")
        print(f"{'=' * 40}")
        print(f"  Trades used  : {est.n_trades}  ({'prior-blended' if est.used_prior else 'data-driven'})")
        print(f"  Win rate (p) : {est.p:.3f}  ({est.n_wins}W / {est.n_losses}L)")
        print(f"  Payoff (b)   : {est.b:.3f}  (avg win ${est.avg_win_usd:.2f} / avg loss ${est.avg_loss_usd:.2f})")
        print(f"  Kelly f*     : {est.kelly_fraction:.4f}")
        print(f"  Half-Kelly   : {est.kelly_fraction * est.params.fraction_multiplier:.4f}")
        print()
        if est.used_prior:
            print(f"  ⚠  Only {est.n_trades} trades — blended with prior (p={config.prior_p}, b={config.prior_b})")
            print(f"     Need {config.min_trades}+ trades for pure data-driven estimate.")
        print()

    db.close()
    return 0


def _cmd_positions_close(ctx: CliContext, args: argparse.Namespace) -> int:
    """Close an open position by ID."""
    from engine.core.config import Config
    from engine.core.database import Database
    from engine.execution.pnl import PnLTracker

    repo_root = ctx.repo_root
    cfg_path = repo_root / "config" / "user.yaml"
    config = Config.from_yaml(cfg_path) if cfg_path.exists() else Config.from_repo_defaults(repo_root)
    db = Database(_resolve_db_path(repo_root, config))
    tracker = PnLTracker(db, config)

    position_id = str(args.position_id)
    exit_price: float | None = getattr(args, "exit_price", None)

    # Resolve exit price from market if not provided
    if exit_price is None:
        row = db.fetchone("SELECT asset FROM positions WHERE id = ? AND status = 'open'", (position_id,))
        if row is None:
            print(f"error: position not found or not open: {position_id}", file=sys.stderr)
            return 1
        asset = str(row[0]).upper()
        try:
            from engine.brain.orchestrator import BrainOrchestrator
            from engine.security.identity import generate_node_identity

            _orch = BrainOrchestrator(config=config, db=db, identity=generate_node_identity())
            exit_price = _orch._resolve_mid_price(asset)
        except Exception:
            pass

    if exit_price is None:
        print("error: could not resolve market price; provide --exit-price", file=sys.stderr)
        return 1

    try:
        tracker.close_position(position_id=position_id, exit_price=float(exit_price), reason="manual_close")
    except Exception as e:
        print(f"error closing position {position_id}: {e}", file=sys.stderr)
        return 1

    out = {"status": "ok", "position_id": position_id, "exit_price": float(exit_price), "reason": "manual_close"}
    if bool(getattr(args, "json", False)):
        print(_json_dumps(out))
    else:
        print(f"closed position {position_id} at {exit_price:.4f}")
    return 0


def _cmd_positions(ctx: CliContext, args: argparse.Namespace) -> int:
    # Dispatch to subcommand if given
    positions_cmd = getattr(args, "positions_cmd", None)
    if positions_cmd == "close":
        return _cmd_positions_close(ctx, args)

    from engine.core.database import Database
    from engine.execution.pnl import PnLTracker

    repo_root = ctx.repo_root
    db = Database(_resolve_db_path(repo_root))
    tracker = PnLTracker(db)

    mark = _latest_mark_prices(db)
    rows = db.fetchall(
        "SELECT id, asset, direction, entry_price, size_notional, leverage, opened_at FROM positions WHERE status = 'open' ORDER BY opened_at DESC"
    )

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
    from datetime import datetime

    try:
        from datetime import UTC  # py311+
    except ImportError:  # pragma: no cover
        from datetime import timezone as _tz  # noqa: PLC0415

        UTC = _tz.utc  # noqa: N806, UP017

    from engine.core.database import Database

    def ensure_endpoint_column(db: Database) -> None:
        cols = [str(r[1]) for r in db.fetchall("PRAGMA table_info(producer_health)")]
        with db._lock, db.conn:
            if "endpoint" not in cols:
                db.execute("ALTER TABLE producer_health ADD COLUMN endpoint TEXT")
            if "quarantined_until" not in cols:
                db.execute("ALTER TABLE producer_health ADD COLUMN quarantined_until TEXT")
            if "quarantined_reason" not in cols:
                db.execute("ALTER TABLE producer_health ADD COLUMN quarantined_reason TEXT")

    repo_root = ctx.repo_root
    db = Database(_resolve_db_path(repo_root))
    ensure_endpoint_column(db)

    cmd = str(getattr(args, "producers_cmd", "") or "")
    if not cmd:
        print("error: missing producers subcommand (register|list|remove)", file=sys.stderr)
        return 2

    if cmd == "register":
        name = str(args.name)
        domain = str(args.domain)
        endpoint = str(args.endpoint)

        from engine.security.ssrf import check_url

        url_check = check_url(endpoint)
        if not url_check.allowed:
            print(f"error: endpoint blocked ({url_check.reason})", file=sys.stderr)
            return 1
        schedule = str(args.schedule)

        now = datetime.now(tz=UTC).isoformat()
        existing = db.fetchone("SELECT name FROM producer_health WHERE name = ?", (name,))
        if existing is not None:
            print(f"error: producer already registered: {name}", file=sys.stderr)
            return 1

        with db._lock, db.conn:
            db.execute(
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
        rows = db.fetchall("SELECT name, domain, schedule, endpoint, updated_at FROM producer_health ORDER BY name ASC")
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
        with db._lock, db.conn:
            cur = db.execute("DELETE FROM producer_health WHERE name = ?", (name,))
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
    db = Database(_resolve_db_path(repo_root))

    cfg_path = repo_root / "config" / "user.yaml"
    config = Config.from_yaml(cfg_path) if cfg_path.exists() else Config.from_repo_defaults(repo_root)

    cmd = str(getattr(args, "contributors_cmd", "") or "")

    reg = _build_contributor_registry_with_eas(db=db, config=config)
    scoring = ContributorScoring(db)

    if cmd == "list":
        items = reg.list_all()
        if bool(getattr(args, "json", False)):
            print(_json_dumps([asdict(c) for c in items]))
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

        from dataclasses import asdict as _asdict

        print(_json_dumps({"status": "ok", "contributor": _asdict(c)}))
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
            print(_json_dumps(asdict(s)))
        else:
            print(f"score: {s.score:.2f} (hit_rate={s.hit_rate:.2%}, submitted={s.signals_submitted}, accepted={s.signals_accepted}, streak={s.streak})")
        return 0

    if cmd == "leaderboard":
        limit = int(getattr(args, "limit", 20) or 20)
        items = scoring.leaderboard(limit=limit)
        if bool(getattr(args, "json", False)):
            print(_json_dumps([asdict(s) for s in items]))
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
        db = Database(_resolve_db_path(repo_root))
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
    """Construct a ContributorRegistry wired with EAS client and GitHub publisher."""

    from engine.core.contributors import ContributorRegistry

    # GitHub publisher — active when token OR GitHub App is configured (fail-open)
    github_publisher: object | None = None
    pub_cfg = config.publish.github
    if pub_cfg.token or (int(pub_cfg.app_id or 0) > 0):
        from engine.integrations.github_publish import make_publisher

        app_auth = None
        if int(pub_cfg.app_id or 0) > 0:
            try:
                from engine.integrations.github_app import GitHubAppAuth

                app_auth = GitHubAppAuth.from_env()
            except Exception:
                pass

        github_publisher = make_publisher(
            owner=pub_cfg.owner,
            repo=pub_cfg.repo,
            token=str(pub_cfg.token or ""),
            labels=pub_cfg.labels,
            app_auth=app_auth,
        )

    # EAS client — only when explicitly enabled
    eas_client: object | None = None
    try:
        from engine.integrations.eas import EASClient

        if bool(config.eas.enabled):
            eas_client = EASClient(
                rpc_url=str(config.eas.rpc_url),
                eas_address=str(config.eas.eas_contract),
                schema_registry_address=str(config.eas.schema_registry),
                private_key=str(config.eas.attester_private_key),
            )
    except Exception:
        pass

    return ContributorRegistry(db, eas_client=eas_client, github_publisher=github_publisher)


def _cmd_webhooks(ctx: CliContext, args: argparse.Namespace) -> int:
    from engine.core.database import Database
    from engine.core.webhooks import add_webhook_subscription, list_webhook_subscriptions, remove_webhook_subscription

    repo_root = ctx.repo_root
    db = Database(_resolve_db_path(repo_root))

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
            print(_json_dumps([asdict(s) for s in subs]))
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


def _kill_switch_state(db) -> dict[str, Any]:
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
    db = Database(_resolve_db_path(repo_root))

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
    db = Database(_resolve_db_path(repo_root))

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
    rows = db.fetchall(
        "SELECT name, domain, consecutive_failures, last_error, last_run_at FROM producer_health WHERE consecutive_failures > 0 OR last_error IS NOT NULL"
    )
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
    pos = db.fetchall(
        "SELECT asset, direction, stop_loss, take_profit, opened_at, id "
        "FROM positions "
        "WHERE status = 'open' AND (stop_loss IS NOT NULL OR take_profit IS NOT NULL)"
    )
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

    db_path = _resolve_db_path(repo_root)
    db_ok = db_path.exists()

    chain_ok = None
    if db_ok:
        try:
            db = Database(db_path)
            chain_ok = bool(db.verify_hash_chain(fast=True))
        except Exception:  # noqa: BLE001
            chain_ok = False

    try:
        ks = Keystore.default()
        ks_info = {"describe": ks.describe()}
    except Exception:  # noqa: BLE001
        ks_info = {"describe": "⚠ keystore unavailable"}

    # Brain cycle freshness
    stale_threshold_minutes = 30
    cycle_age_minutes = None
    brain_cycle_status = "unknown"
    if db_ok and db is not None:
        try:
            last_cycle = db.fetchone("SELECT ts FROM events WHERE type = 'brain.cycle.v1' ORDER BY ts DESC LIMIT 1")
            if last_cycle:
                from datetime import datetime

                try:
                    from datetime import UTC  # py311+
                except ImportError:  # pragma: no cover
                    from datetime import timezone

                    UTC = timezone.utc  # noqa: N806,E702,UP017,I001
                last_ts = datetime.fromisoformat(str(last_cycle[0]).replace("Z", "+00:00"))
                if last_ts.tzinfo is None:
                    last_ts = last_ts.replace(tzinfo=UTC)
                cycle_age_minutes = (datetime.now(UTC) - last_ts).total_seconds() / 60
                brain_cycle_status = "stale" if cycle_age_minutes > stale_threshold_minutes else "ok"
        except Exception:  # noqa: BLE001
            pass

    # Kill switch state
    kill_switch_level = 0
    kill_switch_active = False
    if db_ok and db is not None:
        try:
            ks_row = db.fetchone("SELECT payload FROM events WHERE type = 'system.kill_switch.v1' ORDER BY ts DESC LIMIT 1")
            if ks_row:
                ks_payload = json.loads(ks_row[0])
                kill_switch_level = int(ks_payload.get("level", 0))
                kill_switch_active = kill_switch_level > 0
        except Exception:  # noqa: BLE001
            pass

    # Overall health: degrade on stale cycle or active kill switch
    base_ok = bool(cfg_ok) and bool(db_ok) and (chain_ok is not False)
    degraded = brain_cycle_status == "stale" or kill_switch_active
    overall_status = "ok" if (base_ok and not degraded) else "degraded" if base_ok else "unhealthy"

    payload = {
        "ok": bool(cfg_ok) and bool(db_ok) and (chain_ok is not False),
        "status": overall_status,
        "uptime_s": float(time.monotonic() - start),
        "config": {"path": str(cfg_path), "present": bool(cfg_path.exists()), "ok": bool(cfg_ok), "error": cfg_error},
        "db": {"path": str(db_path), "present": bool(db_ok), "hash_chain_ok": chain_ok},
        "brain_cycle_status": brain_cycle_status,
        "brain": {
            "last_cycle_age_minutes": cycle_age_minutes,
            "cycle_status": brain_cycle_status,
            "stale_threshold_minutes": stale_threshold_minutes,
        },
        "kill_switch": {
            "level": kill_switch_level,
            "active": kill_switch_active,
            **({"status": "active"} if kill_switch_active else {}),
        },
        "identity": identity_status(),
        "keystore": ks_info,
    }

    # health always returns JSON (suitable for cron/heartbeat)
    print(_json_dumps(payload))
    return 0


# Stoic accounting: predictions make claims, outcomes settle them.
# This command turns elapsed forecasts into receipts.
def _cmd_resolve_outcomes(ctx: CliContext, args: argparse.Namespace) -> int:
    """Resolve eligible forecasts into FORECAST_OUTCOME_V1 events.

    Exit code is always 0 (cron/monitoring friendly).
    """

    from engine.brain.outcome_resolver import OutcomeResolver
    from engine.core.config import Config
    from engine.core.database import Database

    repo_root = ctx.repo_root
    db = Database(_resolve_db_path(repo_root))

    # --- Wire up on-chain karma writer (fail-open) ---
    karma_chain_writer = None
    try:
        cfg_path = repo_root / "config" / "user.yaml"
        cfg = Config.from_yaml(cfg_path) if cfg_path.exists() else Config.from_repo_defaults(repo_root)
        if cfg.onchain.enabled and cfg.onchain.rpc_url and cfg.onchain.private_key.get_secret_value():
            from engine.oracle.chain import ChainClient

            chain_client = ChainClient(
                rpc_url=cfg.onchain.rpc_url,
                private_key=cfg.onchain.private_key.get_secret_value(),
                identity_registry_address=cfg.onchain.identity_registry_address,
                reputation_registry_address=cfg.onchain.reputation_registry_address,
                validation_registry_address=cfg.onchain.validation_registry_address,
                public_base_url=cfg.onchain.public_base_url,
            )
            if chain_client.enabled:
                from engine.brain.karma_chain import KarmaChainWriter

                karma_chain_writer = KarmaChainWriter(chain_client=chain_client, db=db)
    except Exception:
        karma_chain_writer = None  # fail-open

    resolved = 0
    skipped = 0
    try:
        resolver = OutcomeResolver(db, karma_chain_writer=karma_chain_writer)
        resolved = int(resolver.resolve_pending())
        skipped = int(getattr(resolver, "last_skipped_missing_price", 0))
    except Exception:
        # Never fail this command; resolver itself is best-effort.
        resolved = 0
        skipped = 0

    # --- Flush on-chain karma writes ---
    karma_tx_hashes: list[str] = []
    if karma_chain_writer:
        with contextlib.suppress(Exception):
            karma_tx_hashes = karma_chain_writer.flush() or []

    # --- SPI signal resolution (Phase 1B) ---
    spi_resolved = 0
    spi_expired = 0
    try:
        from engine.spi.resolution import resolve_expired_signals

        outcomes = resolve_expired_signals(db)
        for outcome in outcomes:
            if outcome.status == "resolved":
                spi_resolved += 1
            elif outcome.status == "expired":
                spi_expired += 1
    except Exception:
        # Never fail this command; SPI resolver is also best-effort.
        pass

    if bool(getattr(args, "json", False)):
        print(
            _json_dumps(
                {
                    "resolved": resolved,
                    "skipped_missing_price": skipped,
                    "spi_resolved": spi_resolved,
                    "spi_expired": spi_expired,
                    "karma_tx_hashes": karma_tx_hashes,
                }
            )
        )
    else:
        parts = [f"resolved {resolved} forecasts"]
        if skipped:
            parts.append(f"skipped {skipped} (missing price data)")
        if spi_resolved or spi_expired:
            parts.append(f"SPI: {spi_resolved} resolved, {spi_expired} expired")
        if karma_tx_hashes:
            parts.append(f"karma on-chain: {len(karma_tx_hashes)} tx")
        print(", ".join(parts))
    return 0


def _cmd_resolve_spi(ctx: CliContext, args: argparse.Namespace) -> int:
    """Resolve expired SPI signals against market outcomes. Exit code 0."""

    from engine.core.database import Database
    from engine.spi.resolution import resolve_expired_signals

    db = Database(_resolve_db_path(ctx.repo_root))

    spi_resolved = 0
    spi_expired = 0
    try:
        outcomes = resolve_expired_signals(db)
        for outcome in outcomes:
            if outcome.status == "resolved":
                spi_resolved += 1
            elif outcome.status == "expired":
                spi_expired += 1
    except Exception as exc:
        if bool(getattr(args, "json", False)):
            print(_json_dumps({"error": str(exc)}))
        else:
            print(f"SPI resolution failed: {exc}")
        return 0

    if bool(getattr(args, "json", False)):
        print(_json_dumps({"spi_resolved": spi_resolved, "spi_expired": spi_expired}))
    else:
        print(f"SPI: {spi_resolved} resolved, {spi_expired} expired")
    return 0


def _cmd_monitor_positions(ctx: CliContext, args: argparse.Namespace) -> int:
    """Evaluate stop/target/time-stop for every open position. Exit code 0."""
    from engine.core.database import Database
    from engine.execution.position_monitor import monitor_positions

    db = Database(_resolve_db_path(ctx.repo_root))
    config = _load_config(ctx)

    result: dict = {"evaluated": 0, "closed_stop": 0, "closed_target": 0, "closed_time_stop": 0, "errors": 0}
    try:
        result = monitor_positions(db, config)
    except Exception as exc:
        if bool(getattr(args, "json", False)):
            print(_json_dumps({"error": str(exc), **result}))
        else:
            print(f"monitor-positions failed: {exc}", file=sys.stderr)
        return 0

    if bool(getattr(args, "json", False)):
        print(_json_dumps(result))
    else:
        closed = result["closed_stop"] + result["closed_target"] + result["closed_time_stop"]
        print(
            f"position-monitor: evaluated={result['evaluated']} "
            f"closed_stop={result['closed_stop']} "
            f"closed_target={result['closed_target']} "
            f"closed_time_stop={result['closed_time_stop']} "
            f"errors={result['errors']}"
        )
        if closed:
            print(f"  ✓ {closed} position(s) auto-closed")
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
    if action == "restore":
        return _identity_restore(ctx, args)

    print("error: missing identity subcommand (forge/show/restore)", file=sys.stderr)
    return 2


def _identity_restore(ctx: CliContext, args: argparse.Namespace) -> int:
    """Restore identity from Ethereum private key via HKDF re-derivation."""

    from engine.security.identity import NodeIdentity, derive_ed25519_from_eth

    use_json = bool(getattr(args, "json", False))
    eth_key_hex = str(getattr(args, "eth_key", "") or "").strip()

    if not eth_key_hex:
        err = "error: --eth-key is required"
        if use_json:
            print(_json_dumps({"ok": False, "error": err}))
        else:
            print(err, file=sys.stderr)
        return 2

    # Strip 0x prefix if present
    eth_key_hex = eth_key_hex.removeprefix("0x")

    # Validate length (32 bytes = 64 hex chars)
    if len(eth_key_hex) != 64:
        err = f"error: eth-key must be 64 hex characters (32 bytes), got {len(eth_key_hex)}"
        if use_json:
            print(_json_dumps({"ok": False, "error": err}))
        else:
            print(err, file=sys.stderr)
        return 2

    try:
        from cryptography.hazmat.primitives import serialization

        priv_ed, pub_ed = derive_ed25519_from_eth(eth_key_hex)

        pub_raw = pub_ed.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        priv_raw = priv_ed.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )

        # Derive node_id from public key material (no optional deps required)
        from datetime import datetime

        try:
            from datetime import UTC  # py311+
        except ImportError:  # pragma: no cover
            from datetime import timezone as _tz  # noqa: PLC0415

            UTC = _tz.utc  # noqa: N806, UP017

        node_id = f"b1e55ed-{pub_raw.hex()[:8]}"
        created_at = datetime.now(tz=UTC).isoformat()

        identity = NodeIdentity(
            node_id=node_id,
            public_key=pub_raw.hex(),
            private_key=priv_raw.hex(),
            created_at=created_at,
            eth_address="",
            eth_private_key=eth_key_hex,
        )

        identity_path = _identity_dir(ctx) / "identity.key"
        identity.save(identity_path)

    except Exception as e:  # noqa: BLE001
        err = f"error: restore failed: {e}"
        if use_json:
            print(_json_dumps({"ok": False, "error": str(e)}))
        else:
            print(err, file=sys.stderr)
        return 1

    if use_json:
        out = {
            "ok": True,
            "node_id": identity.node_id,
            "public_key": identity.public_key,
            "eth_address": identity.eth_address,
            "path": str(identity_path),
        }
        print(_json_dumps(out))
    else:
        print()
        print("  Identity restored.")
        print()
        print(f"  node_id:    {identity.node_id}")
        print(f"  public_key: {identity.public_key[:16]}...")
        if identity.eth_address:
            print(f"  eth_address: {identity.eth_address}")
        print(f"  path:       {identity_path}")
        print()
        print("  Your node_id and public key are identical to the originals.")
        print("  No re-registration is needed.")
        print()
    return 0


def _format_elapsed(seconds: float) -> str:
    s = int(seconds)
    m, s = divmod(s, 60)
    if m <= 0:
        return f"{s}s"
    return f"{m}m {s}s"


def _identity_show(ctx: CliContext, args: argparse.Namespace) -> int:
    use_json = bool(getattr(args, "json", False))

    identity_path = _identity_dir(ctx) / "identity.json"
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


def _find_rust_forge_binary(repo_root: Path) -> str | None:
    """Return path to the Rust forge binary if available, else None."""
    import shutil

    candidates = [
        Path.home() / ".local" / "share" / "b1e55ed" / "bin" / "b1e55ed-forge",
        Path.home() / ".local" / "bin" / "b1e55ed-forge",
    ]
    for p in candidates:
        if p.exists() and os.access(str(p), os.X_OK):
            return str(p)
    found = shutil.which("b1e55ed-forge")
    if found:
        return found
    # Also check in-repo build artifact
    repo_binary = repo_root / "tools" / "forge" / "target" / "release" / "b1e55ed-forge"
    if repo_binary.exists() and os.access(str(repo_binary), os.X_OK):
        return str(repo_binary)
    return None


def _print_forge_binary_instructions() -> None:
    """Print instructions to download the Rust forge binary."""
    print()
    print("  Download the Rust grinder for your platform:")
    print()
    print("    macOS (universal): https://github.com/P-U-C/b1e55ed/releases/latest/download/b1e55ed-forge-macos")
    print("    Linux x86_64: https://github.com/P-U-C/b1e55ed/releases/latest/download/b1e55ed-forge-linux-x86_64")
    print()
    print("  Install:")
    print("    mkdir -p ~/.local/share/b1e55ed/bin")
    print("    curl -Lo ~/.local/share/b1e55ed/bin/b1e55ed-forge <url-for-your-platform>")
    print("    chmod +x ~/.local/share/b1e55ed/bin/b1e55ed-forge")
    print()
    print("  Then re-run: b1e55ed identity forge")
    print()


def _identity_forge(ctx: CliContext, args: argparse.Namespace) -> int:
    """The Forge — identity derivation ritual."""

    import subprocess
    import time

    use_json = bool(getattr(args, "json", False))
    threads = int(getattr(args, "threads", None) or (os.cpu_count() or 4))
    prefix = "b1e55ed"

    # Expected candidates for 7 hex chars
    expected = 16 ** len(prefix)

    rust_binary = _find_rust_forge_binary(ctx.repo_root)

    # If Rust binary not found and not JSON mode, warn and offer options
    if rust_binary is None and not use_json:
        print()
        print("  ⚠ Rust grinder not found — vanity forge requires the b1e55ed-forge binary.")
        print()
        print("  Options:")
        print("    1) Download forge binary   — fast (~2-10s), then forge immediately")
        print("    2) Force Python fallback   — ~90 min, not recommended (no random address)")
        print()

        try:
            choice = input("  Choice [1]: ").strip() or "1"
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if choice != "2":
            # Default: option 1 — download instructions, then exit so user installs and re-runs
            _print_forge_binary_instructions()
            return 0

        # choice == "2": force Python grinder below (rust_binary stays None)
        print()
        print("  ⚠ Starting Python grinder — this will take ~90 minutes.")
        print("    The b1e55ed prefix is non-negotiable; no random address will be generated.")
        print()

    if not use_json:
        print()
        print("  ╔══════════════════════════════════════════╗")
        print("  ║               THE FORGE                  ║")
        print("  ║       b1e55ed identity protocol          ║")
        print("  ╚══════════════════════════════════════════╝")
        print()
        print(f"  Every address in this network begins with 0x{prefix}.")
        print("  Yours is being derived now.")
        print()
        if rust_binary:
            print("  This takes seconds to ~2 min with the Rust grinder (hardware dependent).")
        else:
            print("  Rust grinder not found — using Python fallback (~90 min).")
        print()
        print("  Searching...")
        print()

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
        # macOS: clear quarantine bit so Gatekeeper doesn't silently kill the binary
        if sys.platform == "darwin":
            subprocess.run(
                ["xattr", "-dr", "com.apple.quarantine", rust_binary],
                check=False,
                capture_output=True,
            )
        try:
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
        except OSError:
            # Binary can't be executed — fall through to Python
            rust_binary = None

    if not rust_binary:
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

    identity_dir = _identity_dir(ctx)
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

    # Write identity.key — encrypted Ed25519 key derived from forge key (#299)
    try:
        from engine.security.identity import generate_node_identity

        node_ident = generate_node_identity(eth_private_key=private_key, eth_address=address)
        identity_key_path = identity_dir / "identity.key"
        node_ident.save(identity_key_path)
    except Exception as exc:  # noqa: BLE001
        if not use_json:
            print(f"  ⚠ Could not write identity.key: {exc}", file=sys.stderr)

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
                        "version": "1.0.0-beta.4",
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
    print("  Back it up — your Ed25519 identity is deterministically recoverable")
    print("  from this key via: b1e55ed identity restore --eth-key <hex>")
    print()
    print("  Welcome to the upper class.")
    print()
    print("  ──────────────────────────────────────")
    print()
    return 0


def _cmd_start(ctx: CliContext, args: argparse.Namespace) -> int:
    """Start API + dashboard as background processes, then tail their logs."""
    import contextlib
    import signal
    import socket
    import subprocess as _sp
    import sys
    import time

    host = args.host
    api_port = args.api_port
    dash_port = args.dashboard_port
    open_browser = not args.no_browser

    # --- #301: Check if ports are already in use before starting ---
    for port in (api_port, dash_port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            if sock.connect_ex((host if host != "0.0.0.0" else "127.0.0.1", port)) == 0:
                print()
                # 0xb1e55ed — the port is bound, the oracle breathes
                print(f"  b1e55ed is already running (port {port} is in use).")
                print("  Use 'b1e55ed status' or 'b1e55ed health' to inspect.")
                print()
                return 0

    api_url = f"http://{host}:{api_port}"
    dash_url = f"http://{host}:{dash_port}"

    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║         b1e55ed — starting up           ║")
    print("  ╚══════════════════════════════════════════╝")
    print()
    print(f"  API        → {api_url}")
    print(f"  Dashboard  → {dash_url}")
    print(f"  API docs   → {api_url}/docs")
    print()
    print("  Press Ctrl+C to stop both servers.")
    print()

    exe = sys.executable
    child_env = os.environ.copy()
    child_env.setdefault("B1E55ED_REPO_ROOT", str(ctx.repo_root))
    child_cwd = str(ctx.repo_root)

    api_proc = _sp.Popen(
        [exe, "-m", "uvicorn", "api.main:app", "--host", host, "--port", str(api_port), "--log-level", "warning"],
        stdout=_sp.PIPE,
        stderr=_sp.STDOUT,
        text=True,
        cwd=child_cwd,
        env=child_env,
    )
    dash_proc = _sp.Popen(
        [exe, "-m", "uvicorn", "dashboard.app:app", "--host", host, "--port", str(dash_port), "--log-level", "warning"],
        stdout=_sp.PIPE,
        stderr=_sp.STDOUT,
        text=True,
        cwd=child_cwd,
        env=child_env,
    )

    # Wait a moment then open browser
    if open_browser:
        time.sleep(1.5)
        import webbrowser

        webbrowser.open(dash_url)

    procs = [api_proc, dash_proc]
    labels = [f"[api:{api_port}]", f"[dash:{dash_port}]"]

    def _stop(sig: int, frame: object) -> None:  # noqa: ARG001
        print("\n  Stopping…")
        for p in procs:
            p.terminate()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    import select

    fds = [p.stdout for p in procs if p.stdout]
    fd_label = {p.stdout.fileno(): lbl for p, lbl in zip(procs, labels, strict=False) if p.stdout}

    startup_failed = False

    while True:
        exit_codes = [p.poll() for p in procs]
        if any(code not in (None, 0) for code in exit_codes):
            startup_failed = True
            for p in procs:
                if p.poll() is None:
                    p.terminate()
            break

        # Check if both died
        if all(code is not None for code in exit_codes):
            break

        if not fds:
            time.sleep(0.1)
            continue

        try:
            readable, _, _ = select.select(fds, [], [], 0.5)
        except (ValueError, OSError):
            break

        for fd in readable:
            line = fd.readline()
            if line:
                print(f"  {fd_label.get(fd.fileno(), '')} {line}", end="")
            else:
                # EOF: stop selecting this fd to avoid busy loops when one child exits.
                with contextlib.suppress(ValueError):
                    fds.remove(fd)

    final_codes: list[int] = []
    for p in procs:
        rc = p.poll()
        if rc is None:
            with contextlib.suppress(Exception):
                p.terminate()
            try:
                rc = p.wait(timeout=2)
            except _sp.TimeoutExpired:
                p.kill()
                rc = p.wait(timeout=2)
        final_codes.append(int(rc))

    if startup_failed or any(code != 0 for code in final_codes):
        print("\n  One or more services failed to start.")
        for lbl, code in zip(labels, final_codes, strict=False):
            if code != 0:
                print(f"  {lbl} exited with code {code}")
        return 1

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


def _cmd_daemon(ctx: CliContext, args: argparse.Namespace) -> int:
    if getattr(args, "status", False):
        from engine.cli.commands.daemon import _show_status

        return _show_status()

    from engine.core.config import Config

    repo_root = ctx.repo_root
    cfg_path = repo_root / "config" / "user.yaml"
    config = Config.from_yaml(cfg_path) if cfg_path.exists() else Config.from_repo_defaults(repo_root)

    from engine.cli.commands.daemon import run_daemon

    return run_daemon(repo_root, config)


def _cmd_register(ctx: CliContext, args: argparse.Namespace) -> int:
    """Register this node on-chain via ERC-8004 identity registry."""
    from engine.core.config import Config

    repo_root = ctx.repo_root
    cfg_path = repo_root / "config" / "user.yaml"
    cfg = Config.from_yaml(cfg_path) if cfg_path.exists() else Config.from_repo_defaults(repo_root)
    as_json = getattr(args, "json", False)

    # Already registered?
    if cfg.onchain.system_agent_id != 0:
        msg = f"Already registered (agentId={cfg.onchain.system_agent_id})"
        if as_json:
            print(_json_dumps({"status": "already_registered", "agent_id": cfg.onchain.system_agent_id}))
        else:
            print(f"⚠ {msg}")
        return 1

    # Chain configured?
    if not cfg.onchain.enabled or not cfg.onchain.identity_registry_address:
        msg = "identity_registry_address not set in config — enable onchain and set the registry address first"
        if as_json:
            print(_json_dumps({"status": "error", "message": msg}))
        else:
            print(f"error: {msg}")
        return 1

    # Build agent URI
    agent_uri = cfg.onchain.public_base_url.rstrip("/") + "/.well-known/agent-registration.json"
    if not cfg.onchain.public_base_url:
        agent_uri = f"b1e55ed://{cfg.onchain.network}/node"

    # Register
    from engine.oracle.chain import ChainClient

    client = ChainClient(
        rpc_url=cfg.onchain.rpc_url,
        private_key=cfg.onchain.private_key.get_secret_value(),
        identity_registry_address=cfg.onchain.identity_registry_address,
        public_base_url=cfg.onchain.public_base_url,
    )

    if not client.enabled:
        msg = "Chain client failed to initialise — check rpc_url and private_key"
        if as_json:
            print(_json_dumps({"status": "error", "message": msg}))
        else:
            print(f"error: {msg}")
        return 1

    agent_id = client.register_producer(agent_uri)
    if agent_id is None:
        msg = "Registration transaction failed — check logs for details"
        if as_json:
            print(_json_dumps({"status": "error", "message": msg}))
        else:
            print(f"error: {msg}")
        return 1

    if as_json:
        print(_json_dumps({"status": "ok", "agent_id": agent_id, "agent_uri": agent_uri}))
    else:
        print(f"✅ Registered on-chain — agentId={agent_id}")
        print(f"   agentURI: {agent_uri}")
        print(f"   Update config: onchain.system_agent_id = {agent_id}")

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

    db_path = _resolve_db_path(repo_root)
    db_status = "present" if db_path.exists() else "missing"

    try:
        ks = Keystore.default()
        ks_display = ks.describe()
    except Exception:  # noqa: BLE001
        ks_display = "⚠ keystore unavailable"

    # --- #302: Surface API auth token (masked) ---
    auth_token_display = "(not set)"
    try:
        from engine.core.config import Config as _Cfg

        _config = _Cfg.from_yaml(cfg) if cfg.exists() else None
        if _config and _config.api.auth_token:
            tok = _config.api.auth_token
            auth_token_display = tok[:8] + "..." if len(tok) > 8 else tok
    except Exception:
        auth_token_display = "(error reading config)"

    print("b1e55ed status")
    print(f"- uptime: {time.monotonic() - start:.3f}s")
    print(f"- config: {config_status}")
    print(f"- db: {db_path} ({db_status})")
    print(f"- identity: {identity_status()}")
    print(f"- keystore: {ks_display}")
    print(f"- api auth token: {auth_token_display}")

    health = "blessed" if cfg.exists() else "degraded"
    print(f"- system health: {health}")

    # --- Karma registration gate check ---
    try:
        from engine.core.config import Config as _CfgReg
        from engine.core.database import Database

        _cfg_reg = _CfgReg.from_yaml(cfg) if cfg.exists() else None
        if _cfg_reg and db_path.exists():
            _db = Database(db_path)
            row = _db.execute("SELECT COALESCE(SUM(karma_amount_usd), 0) FROM karma_intents").fetchone()
            total_karma = float(row[0]) if row else 0.0
            threshold = _cfg_reg.karma.registration_threshold
            chain_configured = bool(_cfg_reg.onchain.enabled and _cfg_reg.onchain.identity_registry_address)
            unregistered = _cfg_reg.onchain.system_agent_id == 0

            if total_karma >= threshold and unregistered and chain_configured:
                is_agent = bool(_cfg_reg.onchain.public_base_url)
                if is_agent:
                    print(f"  ⚠ Agent node has {total_karma:.1f} karma — auto-registration recommended")
                else:
                    print(f"  ⚠ You have {total_karma:.1f} karma — run 'b1e55ed register' to claim it on-chain")
    except Exception:  # noqa: BLE001
        pass  # Best-effort — don't break status on karma check failure

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


def _cmd_prune(ctx: CliContext, args: argparse.Namespace) -> int:
    """Prune old records according to retention policy."""
    from engine.core.config import Config
    from engine.core.database import Database

    repo_root = ctx.repo_root
    cfg_path = repo_root / "config" / "user.yaml"
    config = Config.from_yaml(cfg_path) if cfg_path.exists() else Config.from_repo_defaults(repo_root)
    db = Database(_resolve_db_path(repo_root, config))

    retention = config.retention

    # Apply CLI overrides
    if getattr(args, "events_days", None) is not None:
        from copy import copy

        retention = copy(retention)
        object.__setattr__(retention, "events_keep_days", int(args.events_days))

    dry_run = bool(getattr(args, "dry_run", False))
    as_json = bool(getattr(args, "json", False))

    if dry_run:
        # Count without deleting (approximate — uses same WHERE clause)
        result: dict[str, int] = {}
        result["events"] = (
            db.fetchone(
                "SELECT COUNT(*) FROM events WHERE created_at < datetime('now', ?)",
                (f"-{retention.events_keep_days} days",),
            )
            or (0,)
        )[0]
        result["conviction_scores"] = (
            db.fetchone(
                "SELECT COUNT(*) FROM conviction_scores WHERE created_at < datetime('now', ?) AND outcome IS NOT NULL",
                (f"-{retention.conviction_log_keep_days} days",),
            )
            or (0,)
        )[0]
        result["feature_snapshots"] = (
            db.fetchone(
                "SELECT COUNT(*) FROM feature_snapshots WHERE created_at < datetime('now', ?)",
                (f"-{retention.feature_snapshots_keep_days} days",),
            )
            or (0,)
        )[0]
        result["api_rate_limits"] = (
            db.fetchone(
                "SELECT COUNT(*) FROM api_rate_limits WHERE window_start < strftime('%s','now') - (? * 3600)",
                (retention.api_rate_limits_keep_hours,),
            )
            or (0,)
        )[0]
        out: dict[str, object] = {"dry_run": True, "would_delete": result}
    else:
        deleted = db.prune_old_data(retention)
        out = {"dry_run": False, "deleted": deleted}

    db.close()

    if as_json:
        print(_json_dumps(out))
    else:
        mode = "DRY RUN — would delete" if dry_run else "Deleted"
        _raw_counts = out.get("would_delete") or out.get("deleted") or {}
        counts: dict[str, int] = {str(k): int(v) for k, v in _raw_counts.items()} if isinstance(_raw_counts, dict) else {}
        print(f"b1e55ed prune ({mode}):")
        for table, count in counts.items():
            print(f"  {table}: {count} rows")
        total = sum(counts.values())
        print(f"  total: {total} rows")
        if dry_run:
            print("\n  Run without --dry-run to apply.")
    return 0


def _cmd_replay(ctx: CliContext, args: argparse.Namespace) -> int:
    """Rebuild all projections from event replay."""
    import time

    from engine.core.database import Database
    from engine.core.projections import ProjectionManager

    repo_root = ctx.repo_root
    db = Database(_resolve_db_path(repo_root))

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
    db = Database(_resolve_db_path(repo_root))

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


def _cmd_verify_chain(ctx: CliContext, args: argparse.Namespace) -> int:
    """Run a full (non-fast) hash chain verification and print results."""
    import time

    from engine.core.database import Database

    repo_root = ctx.repo_root
    db = Database(_resolve_db_path(repo_root))

    try:
        t0 = time.monotonic()
        valid = db.verify_hash_chain()  # full scan, no fast=True
        elapsed = time.monotonic() - t0

        result = {
            "status": "ok" if valid else "FAIL",
            "hash_chain": "pass" if valid else "FAIL",
            "elapsed_seconds": round(elapsed, 3),
        }

        if getattr(args, "json", False):
            print(_json_dumps(result))
        else:
            icon = "✅" if valid else "❌"
            print(f"verify-chain: {icon} {'PASS' if valid else 'FAIL'} (full scan, {elapsed:.3f}s)")

        return 0 if valid else 1
    finally:
        db.close()


def _parse_param_spec(spec: str) -> tuple[str, list[Any]]:
    """Parse a ``--param`` value of the form ``name=v1,v2,v3``.

    Values are auto-detected as ``int`` > ``float`` > ``str`` in that order.
    """
    if "=" not in spec:
        raise ValueError(f"Invalid --param spec {spec!r}. Expected format: name=v1,v2,v3")
    name, raw_values = spec.split("=", 1)
    name = name.strip()
    if not name:
        raise ValueError(f"Empty parameter name in --param spec {spec!r}")
    values: list[Any] = []
    for raw in raw_values.split(","):
        raw = raw.strip()
        if not raw:
            continue
        # auto-detect: try int first, then float, else keep as str
        try:
            values.append(int(raw))
            continue
        except ValueError:
            pass
        try:
            values.append(float(raw))
            continue
        except ValueError:
            pass
        values.append(raw)
    if not values:
        raise ValueError(f"No values found in --param spec {spec!r}")
    return name, values


def _handle_backtest_gridsweep(args: argparse.Namespace) -> int:
    """Handle ``b1e55ed backtest gridsweep``."""
    import dataclasses as _dc

    from engine.backtest.engine import BacktestConfig  # noqa: I001
    from engine.backtest.io import load_prices_csv  # noqa: I001
    from engine.backtest.sweep import GridConfig, run_grid_sweep  # noqa: I001

    # --- parse --param specs ---
    raw_params: list[str] = list(getattr(args, "params", []) or [])
    param_grid: dict[str, list[Any]] = {}
    for spec in raw_params:
        try:
            name, values = _parse_param_spec(spec)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if name in param_grid:
            print(f"error: duplicate --param {name!r}. Specify all values in one flag: --param {name}=v1,v2,...", file=sys.stderr)
            return 2
        param_grid[name] = values

    # --- validate param names exist on the strategy ---
    from engine.backtest.sweep import _get_registry  # noqa: I001

    registry = _get_registry()
    strategy_name = str(args.strategy)
    cls = registry.get(strategy_name)
    if cls is None:
        print(f"error: unknown strategy {strategy_name!r}", file=sys.stderr)
        return 2

    known_fields: set[str] = {f.name for f in _dc.fields(cls)}
    for param_name in param_grid:
        if param_name not in known_fields:
            print(
                f"error: strategy {strategy_name!r} has no parameter {param_name!r}. Valid fields: {', '.join(sorted(known_fields))}",
                file=sys.stderr,
            )
            return 2

    # --- load prices ---
    try:
        series = load_prices_csv(str(args.prices))
    except Exception as exc:
        print(f"error loading prices: {exc}", file=sys.stderr)
        return 1

    # --- run sweep ---
    config = GridConfig(strategy=strategy_name, params=param_grid)
    result = run_grid_sweep(
        config=config,
        close=series.close,
        high=series.high,
        low=series.low,
        volume=series.volume,
        train_size=int(args.train),
        test_size=int(args.test),
        step_size=int(args.step),
        embargo=int(args.embargo),
        backtest_cfg=BacktestConfig(fee_bps=float(args.fee_bps)),
        n_boot=int(args.bootstrap),
        seed=int(args.seed),
        q=float(args.q),
    )

    # --- find best by Sharpe ---
    best = max(result.items, key=lambda r: r.oos_sharpe) if result.items else None

    if bool(getattr(args, "json", False)):
        out = {
            "strategy": strategy_name,
            "summary": {
                "total_configs": result.total_configs,
                "fdr_survivors": result.fdr_survivors,
                "q": result.q,
                "best_by_sharpe": {
                    "params": best.params,
                    "oos_sharpe": best.oos_sharpe,
                    "oos_total_return": best.oos_total_return,
                    "bh_fdr_pass": best.bh_fdr_pass,
                }
                if best
                else None,
            },
            "results": [
                {
                    "params": r.params,
                    "oos_total_return": r.oos_total_return,
                    "oos_sharpe": r.oos_sharpe,
                    "oos_max_drawdown": r.oos_max_drawdown,
                    "mean_return": r.mean_return,
                    "p_value": r.p_value,
                    "bh_fdr_pass": r.bh_fdr_pass,
                }
                for r in result.items
            ],
        }
        print(_json_dumps(out))
    else:
        # Human-readable table
        print(f"\nGrid Sweep: {strategy_name}")
        print(f"  Total configs : {result.total_configs}")
        print(f"  FDR survivors : {result.fdr_survivors}  (q={result.q})")
        if best:
            print(f"  Best (Sharpe) : params={best.params}  sharpe={best.oos_sharpe:.4f}  fdr={'PASS' if best.bh_fdr_pass else 'FAIL'}")
        print()
        # Header
        header_params = list(param_grid.keys()) if param_grid else []
        col_widths = {k: max(len(k), 8) for k in header_params}
        hdr = "  ".join(f"{k:>{col_widths[k]}}" for k in header_params)
        print(f"  {hdr}   {'ret%':>8}  {'sharpe':>8}  {'mdd':>8}  {'p_val':>8}  {'fdr':>5}")
        print("  " + "-" * (sum(col_widths.values()) + 2 * len(col_widths) + 50))
        for r in result.items:
            param_part = "  ".join(f"{str(r.params.get(k, '')):>{col_widths[k]}}" for k in header_params)
            fdr_str = "PASS" if r.bh_fdr_pass else "fail"
            print(f"  {param_part}   {r.oos_total_return * 100:>7.2f}%  {r.oos_sharpe:>8.4f}  {r.oos_max_drawdown:>8.4f}  {r.p_value:>8.4f}  {fdr_str:>5}")
        print()

    return 0


def _parse_grid_spec(spec: str) -> tuple[str, dict[str, list[Any]]]:
    """Parse a ``--grid`` value of the form ``strategy:p1=v1,v2;p2=v3,v4``.

    Returns (strategy_name, param_grid).
    """
    if ":" not in spec:
        raise ValueError(f"Invalid --grid spec {spec!r}. Expected format: strategy:param=v1,v2;param2=v3,v4")
    strategy, param_part = spec.split(":", 1)
    strategy = strategy.strip()
    if not strategy:
        raise ValueError(f"Empty strategy name in --grid spec {spec!r}")

    param_grid: dict[str, list[Any]] = {}
    if param_part.strip():
        for param_spec in param_part.split(";"):
            param_spec = param_spec.strip()
            if not param_spec:
                continue
            name, values = _parse_param_spec(param_spec)
            param_grid[name] = values

    return strategy, param_grid


def _handle_backtest_megasweep(args: argparse.Namespace) -> int:
    """Handle ``b1e55ed backtest megasweep``."""
    from engine.backtest.engine import BacktestConfig  # noqa: I001
    from engine.backtest.io import load_prices_csv  # noqa: I001
    from engine.backtest.sweep import GridConfig, MultiSweepResult, get_default_configs, run_multi_sweep  # noqa: I001

    use_defaults = bool(getattr(args, "all_defaults", False))
    raw_grids: list[str] = list(getattr(args, "grids", []) or [])

    if not use_defaults and not raw_grids:
        print("error: must specify --all-defaults or at least one --grid spec", file=sys.stderr)
        return 2

    if use_defaults and raw_grids:
        print("error: --all-defaults and --grid are mutually exclusive", file=sys.stderr)
        return 2

    # --- build configs ---
    configs: list[GridConfig]
    if use_defaults:
        configs = get_default_configs()
    else:
        configs = []
        for raw in raw_grids:
            try:
                strategy, param_grid = _parse_grid_spec(raw)
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            configs.append(GridConfig(strategy=strategy, params=param_grid))

    # --- load prices ---
    try:
        series = load_prices_csv(str(args.prices))
    except Exception as exc:
        print(f"error loading prices: {exc}", file=sys.stderr)
        return 1

    # --- run mega sweep ---
    try:
        result: MultiSweepResult = run_multi_sweep(
            configs=configs,
            close=series.close,
            high=series.high,
            low=series.low,
            volume=series.volume,
            train_size=int(args.train),
            test_size=int(args.test),
            step_size=int(args.step),
            embargo=int(args.embargo),
            backtest_cfg=BacktestConfig(fee_bps=float(args.fee_bps)),
            n_boot=int(args.bootstrap),
            seed=int(args.seed),
            q=float(args.q),
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # --- find best by Sharpe ---
    best = max(result.items, key=lambda r: r.oos_sharpe) if result.items else None
    survivors = [r for r in result.items if r.bh_fdr_pass]
    best_survivor = max(survivors, key=lambda r: r.oos_sharpe) if survivors else None

    if bool(getattr(args, "json", False)):
        out = {
            "summary": {
                "strategies_tested": result.strategies_tested,
                "total_configs": result.total_configs,
                "fdr_survivors": result.fdr_survivors,
                "q": result.q,
                "best_by_sharpe": {
                    "strategy": best.strategy,
                    "params": best.params,
                    "oos_sharpe": best.oos_sharpe,
                    "oos_total_return": best.oos_total_return,
                    "bh_fdr_pass": best.bh_fdr_pass,
                }
                if best
                else None,
                "best_fdr_survivor": {
                    "strategy": best_survivor.strategy,
                    "params": best_survivor.params,
                    "oos_sharpe": best_survivor.oos_sharpe,
                    "oos_total_return": best_survivor.oos_total_return,
                }
                if best_survivor
                else None,
            },
            "results": [
                {
                    "strategy": r.strategy,
                    "params": r.params,
                    "oos_total_return": r.oos_total_return,
                    "oos_sharpe": r.oos_sharpe,
                    "oos_max_drawdown": r.oos_max_drawdown,
                    "mean_return": r.mean_return,
                    "p_value": r.p_value,
                    "bh_fdr_pass": r.bh_fdr_pass,
                }
                for r in result.items
            ],
        }
        print(_json_dumps(out))
    else:
        # Human-readable output
        print(f"\n{'=' * 70}")
        print(f"  MEGA SWEEP — {len(result.strategies_tested)} strategies × {result.total_configs} total configs")
        print(f"{'=' * 70}")
        print(f"  Strategies : {', '.join(result.strategies_tested)}")
        print(f"  FDR survivors : {result.fdr_survivors} / {result.total_configs}  (q={result.q})")
        if best:
            print(f"  Best (Sharpe) : {best.strategy} {best.params}  sharpe={best.oos_sharpe:.4f}  fdr={'PASS' if best.bh_fdr_pass else 'FAIL'}")
        if best_survivor:
            print(f"  Best FDR pass : {best_survivor.strategy} {best_survivor.params}  sharpe={best_survivor.oos_sharpe:.4f}")
        print()

        # Group by strategy
        by_strat: dict[str, list[Any]] = {}
        for r in result.items:
            by_strat.setdefault(r.strategy, []).append(r)

        for strat_name, strat_results in by_strat.items():
            strat_survivors = sum(1 for r in strat_results if r.bh_fdr_pass)
            print(f"  --- {strat_name} ({len(strat_results)} combos, {strat_survivors} FDR pass) ---")
            # Find param keys for this strategy
            all_param_keys: list[str] = []
            for r in strat_results:
                for k in r.params:
                    if k not in all_param_keys:
                        all_param_keys.append(k)
            col_widths = {k: max(len(k), 8) for k in all_param_keys}
            hdr = "  ".join(f"{k:>{col_widths[k]}}" for k in all_param_keys)
            print(f"  {hdr}   {'ret%':>8}  {'sharpe':>8}  {'mdd':>8}  {'p_val':>8}  {'fdr':>5}")
            print("  " + "-" * (sum(col_widths.values()) + 2 * len(col_widths) + 50))
            for r in sorted(strat_results, key=lambda x: x.oos_sharpe, reverse=True):
                param_part = "  ".join(f"{str(r.params.get(k, '')):>{col_widths[k]}}" for k in all_param_keys)
                fdr_str = "PASS" if r.bh_fdr_pass else "fail"
                print(f"  {param_part}   {r.oos_total_return * 100:>7.2f}%  {r.oos_sharpe:>8.4f}  {r.oos_max_drawdown:>8.4f}  {r.p_value:>8.4f}  {fdr_str:>5}")
            print()

    return 0


def _handle_backtest_regime(args: argparse.Namespace) -> int:
    """Handle ``b1e55ed backtest regime``."""
    from engine.backtest.engine import BacktestConfig  # noqa: I001
    from engine.backtest.io import load_prices_csv  # noqa: I001
    from engine.backtest.regime import run_regime_backtest  # noqa: I001
    from engine.backtest.strategies.breakout import BreakoutStrategy  # noqa: I001
    from engine.backtest.strategies.combined import CombinedStrategy  # noqa: I001
    from engine.backtest.strategies.ma_crossover import MACrossoverStrategy  # noqa: I001
    from engine.backtest.strategies.mean_reversion import MeanReversionStrategy  # noqa: I001
    from engine.backtest.strategies.momentum import MomentumStrategy  # noqa: I001
    from engine.backtest.strategies.rsi_reversion import RSIReversionStrategy  # noqa: I001
    from engine.backtest.strategies.trend_following import TrendFollowingStrategy  # noqa: I001
    from engine.backtest.strategies.volatility import VolatilityFilterStrategy  # noqa: I001

    try:
        series = load_prices_csv(str(args.prices))
    except Exception as exc:
        print(f"error loading prices: {exc}", file=sys.stderr)
        return 1

    strat = {
        "momentum": MomentumStrategy(),
        "ma_crossover": MACrossoverStrategy(),
        "rsi_reversion": RSIReversionStrategy(),
        "breakout": BreakoutStrategy(),
        "mean_reversion": MeanReversionStrategy(),
        "trend_following": TrendFollowingStrategy(),
        "volatility": VolatilityFilterStrategy(),
        "combined": CombinedStrategy(),
    }[str(args.strategy)]

    result = run_regime_backtest(
        strategy=strat,
        close=series.close,
        high=series.high,
        low=series.low,
        volume=series.volume,
        cfg=BacktestConfig(fee_bps=float(args.fee_bps)),
        n_boot=int(args.bootstrap),
        seed=int(args.seed),
        q=float(args.q),
    )

    if bool(getattr(args, "json", False)):
        out = {
            "strategy": result.strategy,
            "overall": {"sharpe": result.overall_sharpe, "total_return": result.overall_return},
            "best_regime": result.best_regime,
            "worst_regime": result.worst_regime,
            "regimes": [
                {
                    "regime": r.regime,
                    "n_bars": r.n_bars,
                    "n_trades": r.n_trades,
                    "total_return": r.total_return,
                    "sharpe": r.sharpe,
                    "max_drawdown": r.max_drawdown,
                    "mean_return": r.mean_return,
                    "p_value": r.p_value,
                    "bh_fdr_pass": r.bh_fdr_pass,
                }
                for r in result.regime_results
            ],
        }
        print(_json_dumps(out))
    else:
        print(f"\nRegime-Conditioned Backtest: {result.strategy}")
        print(f"{'=' * 60}")
        print(f"  Overall   : sharpe={result.overall_sharpe:.4f}  ret={result.overall_return * 100:.2f}%")
        if result.best_regime:
            print(f"  Best (FDR): {result.best_regime}")
        if result.worst_regime:
            print(f"  Worst     : {result.worst_regime}")
        print()
        print(f"  {'Regime':<12} {'Bars':>6} {'Trades':>7} {'Ret%':>8} {'Sharpe':>8} {'MDD':>8} {'p-val':>8} {'FDR':>5}")
        print(f"  {'-' * 65}")
        for r in result.regime_results:
            fdr_str = "PASS" if r.bh_fdr_pass else "fail"
            print(
                f"  {r.regime:<12} {r.n_bars:>6} {r.n_trades:>7} "
                f"{r.total_return * 100:>7.2f}% {r.sharpe:>8.4f} {r.max_drawdown:>8.4f} "
                f"{r.p_value:>8.4f} {fdr_str:>5}"
            )
        print()

    return 0


def _cmd_backtest(ctx: CliContext, args: argparse.Namespace) -> int:
    from engine.backtest.engine import BacktestConfig  # noqa: I001
    from engine.backtest.io import load_prices_csv  # noqa: I001
    from engine.backtest.stats import benjamini_hochberg  # noqa: I001
    from engine.backtest.stats import bootstrap_p_value_mean_gt_zero  # noqa: I001
    from engine.backtest.strategies import BreakoutStrategy  # noqa: I001
    from engine.backtest.strategies import CombinedStrategy  # noqa: I001
    from engine.backtest.strategies import MACrossoverStrategy  # noqa: I001
    from engine.backtest.strategies import MeanReversionStrategy  # noqa: I001
    from engine.backtest.strategies import MomentumStrategy  # noqa: I001
    from engine.backtest.strategies import RSIReversionStrategy  # noqa: I001
    from engine.backtest.strategies import TrendFollowingStrategy  # noqa: I001
    from engine.backtest.strategies import VolatilityFilterStrategy  # noqa: I001
    from engine.backtest.walkforward import run_walkforward  # noqa: I001

    cmd = str(getattr(args, "backtest_cmd", "") or "")
    if cmd not in ("walkforward", "gridsweep", "megasweep", "regime"):
        print("error: missing/unknown backtest subcommand (walkforward|gridsweep|megasweep|regime)", file=sys.stderr)
        return 2

    if cmd == "gridsweep":
        return _handle_backtest_gridsweep(args)

    if cmd == "megasweep":
        return _handle_backtest_megasweep(args)

    if cmd == "regime":
        return _handle_backtest_regime(args)

    series = load_prices_csv(str(args.prices))

    strat_name = str(args.strategy)
    strat = {
        "momentum": MomentumStrategy(),
        "ma_crossover": MACrossoverStrategy(),
        "rsi_reversion": RSIReversionStrategy(),
        "breakout": BreakoutStrategy(),
        "mean_reversion": MeanReversionStrategy(),
        "trend_following": TrendFollowingStrategy(),
        "volatility": VolatilityFilterStrategy(),
        "combined": CombinedStrategy(),
    }[strat_name]

    wf = run_walkforward(
        strategy=strat,
        close=series.close,
        high=series.high,
        low=series.low,
        volume=series.volume,
        train_size=int(args.train),
        test_size=int(args.test),
        step_size=int(args.step),
        embargo=int(args.embargo),
        cfg=BacktestConfig(fee_bps=float(args.fee_bps)),
    )

    tr = bootstrap_p_value_mean_gt_zero(wf.combined_oos_returns, n_boot=int(args.bootstrap), seed=int(args.seed))
    fdr_mask = benjamini_hochberg([tr.p_value], q=float(args.q))
    passed = bool(fdr_mask[0]) if fdr_mask else False

    out = {
        "strategy": strat_name,
        "walkforward": {
            "windows": [
                {
                    "train_start": int(w.train_start),
                    "train_end": int(w.train_end),
                    "test_start": int(w.test_start),
                    "test_end": int(w.test_end),
                }
                for w in wf.windows
            ],
            "window_metrics": wf.window_metrics,
            "oos": {
                "total_return": float(wf.combined_oos_equity[-1] - 1.0) if wf.combined_oos_equity.size else 0.0,
            },
        },
        "stats": {
            "mean_return": float(tr.statistic),
            "p_value": float(tr.p_value),
            "bh_fdr_pass": passed,
            "q": float(args.q),
        },
    }

    if bool(getattr(args, "json", False)):
        print(_json_dumps(out))
    else:
        print(_json_dumps(out))

    return 0


def _cmd_reconcile(ctx: CliContext, args: argparse.Namespace) -> int:
    """Backfill provenance events for positions whose events were lost in a crash."""
    from engine.core.database import Database
    from engine.execution.oms import reconcile_execution_events

    repo_root = ctx.repo_root
    db_path = _resolve_db_path(repo_root)
    if not db_path.exists():
        msg = f"error: {db_path} not found. Run `b1e55ed setup` first."
        print(msg, file=sys.stderr)
        return 1

    db = Database(db_path)
    result = reconcile_execution_events(db)
    db.close()

    total = sum(result.values())
    if bool(getattr(args, "json", False)):
        print(_json_dumps({"status": "ok", "repaired": result, "total": total}))
    else:
        print(f"reconcile complete: {total} events backfilled")
        for event_type, count in result.items():
            if count > 0:
                print(f"  {event_type}: {count}")
        if total == 0:
            print("  (nothing to repair)")
    return 0


def _cmd_wizard(ctx: CliContext, args: argparse.Namespace) -> int:
    from engine.cli.commands.wizard import run_wizard

    return run_wizard(ctx, args)


# ---------------------------------------------------------------------------
# SPI helpers
# ---------------------------------------------------------------------------

_SPI_LIFECYCLE_ORDER = ["onboarding", "shadow", "active", "suspended", "retired"]


def _spi_next_state(current: str) -> str | None:
    """Return the next logical promotion state, or None if terminal."""
    promotable = {"onboarding": "shadow", "shadow": "active"}
    return promotable.get(current)


def _spi_config_dir() -> Path:
    """Return ~/.b1e55ed/spi/producers/, creating it if necessary."""
    d = Path.home() / ".b1e55ed" / "spi" / "producers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _spi_register_flow(api_url: str) -> int:
    """Interactive producer registration flow. Returns 0 on success, 1 on error."""
    import urllib.error
    import urllib.request

    print("\n  SPI Producer Registration")
    print("  " + "-" * 40)

    producer_id = input("  Producer ID (slug, e.g. sendoeth): ").strip()
    if not producer_id:
        print("error: producer_id is required", file=sys.stderr)
        return 1

    producer_name = input(f"  Producer name [default: {producer_id} Signal Producer]: ").strip()
    if not producer_name:
        producer_name = f"{producer_id} Signal Producer"

    ingress_mode = _prompt_choice(
        "  Ingress mode",
        choices=["native", "adapter"],
        default="native",
    )

    api_base_url: str | None = None
    if ingress_mode == "adapter":
        api_base_url = input("  API base URL: ").strip() or None

    payload = json.dumps({"producer_id": producer_id, "producer_name": producer_name, "ingress_mode": ingress_mode}).encode()
    req = urllib.request.Request(
        f"{api_url}/api/v1/spi/producers",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            err = json.loads(body)
            msg = err.get("detail", {}).get("message", body) if isinstance(err.get("detail"), dict) else err.get("detail", body)
        except Exception:  # noqa: BLE001
            msg = body
        print(f"error: {exc.code} — {msg}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"error: cannot reach API at {api_url} — {exc.reason}", file=sys.stderr)
        return 1

    api_key = data.get("api_key", "")

    print()
    print("  ┌─────────────────────────────────────────────────────────────┐")
    print("  │  ⚠  STORE THIS KEY — IT WILL NOT BE SHOWN AGAIN            │")
    print("  │                                                             │")
    print(f"  │  {api_key:<59}│")
    print("  └─────────────────────────────────────────────────────────────┘")
    print()

    # Save producer config (without the key)
    try:
        from datetime import UTC  # py311+
    except ImportError:  # pragma: no cover
        from datetime import timezone as _tz  # noqa: PLC0415

        UTC = _tz.utc  # noqa: N806, UP017
    from datetime import datetime

    config_dir = _spi_config_dir()
    config_path = config_dir / f"{producer_id}.json"
    config = {
        "producer_id": producer_id,
        "producer_name": producer_name,
        "ingress_mode": ingress_mode,
        "registered_at": datetime.now(tz=UTC).isoformat(),
        "api_base_url": api_base_url,
    }
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    config_path.chmod(0o600)  # producer config contains sensitive metadata
    print(f"  Config saved → {config_path}")
    print(f"  Producer '{producer_id}' registered successfully.")
    return 0


def _cmd_spi(ctx: CliContext, args: argparse.Namespace) -> int:
    """Dispatch SPI subcommands."""
    import urllib.error
    import urllib.request

    cmd = str(getattr(args, "spi_cmd", "") or "")
    api_url = str(getattr(args, "api_url", "http://127.0.0.1:5050"))

    if not cmd:
        print("error: missing spi subcommand (register|status|promote|test-key)", file=sys.stderr)
        return 2

    if cmd == "register":
        return _spi_register_flow(api_url)

    if cmd == "status":
        req = urllib.request.Request(
            f"{api_url}/api/v1/spi/producers",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                data = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            print(f"error: {exc.code} — {exc.read().decode(errors='replace')}", file=sys.stderr)
            return 1
        except urllib.error.URLError as exc:
            print(f"error: cannot reach API at {api_url} — {exc.reason}", file=sys.stderr)
            return 1

        producers = data.get("producers", [])
        if not producers:
            print("(no registered SPI producers)")
            return 0

        # Fetch karma for each producer to enrich the table
        rows: list[list[str]] = []
        for p in producers:
            pid = p.get("producer_id", "")
            state = p.get("lifecycle_state", "")
            ingress = p.get("ingress_mode", "")
            # Try to get karma details
            karma_str = "-"
            resolved_str = "-"
            try:
                kreq = urllib.request.Request(
                    f"{api_url}/api/v1/spi/producers/{pid}",
                    headers={"Accept": "application/json"},
                    method="GET",
                )
                with urllib.request.urlopen(kreq, timeout=5) as kresp:  # noqa: S310
                    kdata = json.loads(kresp.read())
                    k = kdata.get("running_karma")
                    karma_str = f"{k:.3f}" if k is not None else "-"
                    resolved_str = str(kdata.get("resolved_count", "-"))
            except Exception:  # noqa: BLE001
                pass
            rows.append([pid, state, ingress, karma_str, resolved_str])

        _print_table(["producer_id", "state", "ingress", "karma", "resolved"], rows)
        return 0

    if cmd == "promote":
        producer_id = str(args.producer_id)
        # Get current state first
        req = urllib.request.Request(
            f"{api_url}/api/v1/spi/producers/{producer_id}",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                pdata = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            print(f"error: {exc.code} — {exc.read().decode(errors='replace')}", file=sys.stderr)
            return 1
        except urllib.error.URLError as exc:
            print(f"error: cannot reach API at {api_url} — {exc.reason}", file=sys.stderr)
            return 1

        current_state = pdata.get("lifecycle_state", "")
        next_state = _spi_next_state(current_state)
        if next_state is None:
            print(f"error: producer '{producer_id}' is in terminal state '{current_state}' — cannot promote", file=sys.stderr)
            return 1

        payload = json.dumps({"to_state": next_state}).encode()
        treq = urllib.request.Request(
            f"{api_url}/api/v1/spi/producers/{producer_id}/transition",
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(treq, timeout=10) as tresp:  # noqa: S310
                tdata = json.loads(tresp.read())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            try:
                err = json.loads(body)
                msg = err.get("detail", {}).get("message", body) if isinstance(err.get("detail"), dict) else err.get("detail", body)
            except Exception:  # noqa: BLE001
                msg = body
            print(f"error: {exc.code} — {msg}", file=sys.stderr)
            return 1
        except urllib.error.URLError as exc:
            print(f"error: cannot reach API at {api_url} — {exc.reason}", file=sys.stderr)
            return 1

        prev = tdata.get("previous_state", current_state)
        new = tdata.get("lifecycle_state", next_state)
        print(f"  {producer_id}: {prev} → {new}")
        return 0

    if cmd == "test-key":
        producer_id = str(args.producer_id)
        api_key = getpass.getpass(f"  API key for '{producer_id}': ").strip()
        if not api_key:
            print("error: key is required", file=sys.stderr)
            return 1

        req = urllib.request.Request(
            f"{api_url}/api/v1/spi/signals",
            headers={"Accept": "application/json", "X-Producer-Key": api_key},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                resp.read()  # consume body
            print(f"  Key valid — producer '{producer_id}' authenticated successfully.")
            return 0
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                print("error: key rejected (403 Forbidden) — key may be invalid or producer inactive", file=sys.stderr)
            else:
                print(f"error: {exc.code} — {exc.read().decode(errors='replace')}", file=sys.stderr)
            return 1
        except urllib.error.URLError as exc:
            print(f"error: cannot reach API at {api_url} — {exc.reason}", file=sys.stderr)
            return 1

    print(f"error: unknown spi subcommand: {cmd}", file=sys.stderr)
    return 2


def _cmd_uninstall(ctx: CliContext, args: argparse.Namespace) -> int:
    from engine.cli.commands.uninstall import run_uninstall

    return run_uninstall(ctx, args)


def _cmd_anchor(ctx: CliContext, args: argparse.Namespace) -> int:
    from engine.cli.commands.anchor import run_anchor

    return run_anchor(args, repo_root=ctx.repo_root)


def _cmd_export(ctx: CliContext, args: argparse.Namespace) -> int:
    from engine.cli.commands.export import run_export

    return run_export(args, repo_root=ctx.repo_root)


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
    # Process supervisors (daemon, start) are ungated — identity is checked by sub-processes
    # The conductor doesn't audition. The orchestra does.
    ungated_commands = {"identity", "setup", "wizard", "uninstall", "daemon", "start"}

    # Operational commands are identity-gate exempt — they must run to diagnose the identity itself.
    # An operator with a broken identity still needs doctor/health/integrity to recover.
    # These commands may still REPORT identity status internally, but they must not be blocked.
    identity_gate_exempt = {"health", "doctor", "integrity", "verify-chain", "replay", "prune", "reconcile", "repair"}

    cmd = getattr(args, "command", None)

    # contributors register --node-id bypasses identity gate (explicit identity provided)
    # Wittgenstein: whereof one cannot speak, thereof one must be silent.
    # But you spoke. You gave us the node_id. The gate opens.
    # contributors register --node-id bypasses identity gate (explicit identity provided)
    _contributors_register_with_node_id = (
        cmd == "contributors" and getattr(args, "contributors_cmd", None) == "register" and bool(getattr(args, "node_id", None))
    )

    if cmd not in ungated_commands and cmd not in identity_gate_exempt and not _contributors_register_with_node_id:
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
        "setup": lambda ctx, args: __import__("engine.cli.commands.setup", fromlist=["run_setup"]).run_setup(ctx, args),
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
        "resolve-outcomes": _cmd_resolve_outcomes,
        "resolve-spi": _cmd_resolve_spi,
        "monitor-positions": _cmd_monitor_positions,
        "keys": _cmd_keys,
        "identity": _cmd_identity,
        "start": _cmd_start,
        "api": _cmd_api,
        "dashboard": _cmd_dashboard,
        "daemon": _cmd_daemon,
        "status": _cmd_status,
        "register": _cmd_register,
        "replay": _cmd_replay,
        "integrity": _cmd_integrity,
        "verify-chain": _cmd_verify_chain,
        "reconcile": _cmd_reconcile,
        "backtest": _cmd_backtest,
        "kelly": _cmd_kelly,
        "doctor": lambda ctx, args: __import__("engine.cli.doctor", fromlist=["run_doctor"]).run_doctor(args),
        "anchor": _cmd_anchor,
        "export": _cmd_export,
        "wizard": _cmd_wizard,
        "uninstall": _cmd_uninstall,
        "report": lambda ctx, args: __import__("engine.cli.commands.report", fromlist=["run_report"]).run_report(ctx, args),
        "spi": _cmd_spi,
    }

    fn = dispatch.get(str(args.command))
    if fn is None:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 2

    return int(fn(ctx, args))


if __name__ == "__main__":
    raise SystemExit(main())
