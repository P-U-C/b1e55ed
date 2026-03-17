"""engine.cli.commands.report

b1e55ed report -- stratification and cockpit summary reports.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from typing import Any


def build_report_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = sub.add_parser("report", help="Generate reports")
    p.add_argument("--stratification", action="store_true", help="Show confidence stratification report")
    p.add_argument("--cockpit-summary", action="store_true", help="Show 7-day cockpit summary")
    p.add_argument("--json", action="store_true", help="Output as JSON")
    return p


def run_report(ctx: Any, args: argparse.Namespace) -> int:
    if getattr(args, "stratification", False):
        return _report_stratification(ctx, args)
    if getattr(args, "cockpit_summary", False):
        return _report_cockpit(ctx, args)
    print("Usage: b1e55ed report --stratification | --cockpit-summary")
    return 1


def _report_stratification(ctx: Any, args: argparse.Namespace) -> int:
    from engine.brain.learning import StratificationTracker

    db = ctx.db
    tracker = StratificationTracker(db)
    report = tracker.get_report()

    # Benchmark comparison data — aggregate by benchmark source.
    bm_report = _benchmark_comparison(db)

    if getattr(args, "json", False):
        import json

        print(json.dumps({"stratification": report, "benchmark_comparison": bm_report}, indent=2, default=str))
        return 0

    as_of = report.get("as_of", "")
    print()
    print("Confidence Stratification Report")
    print("=================================")
    print("As of: " + str(as_of))
    print()
    print("{:<10}{:>8}{:>10}{:>10}{:>10}".format("Bucket", "Signals", "With P&L", "Avg P&L", "Win Rate"))
    print("{:<10}{:>8}{:>10}{:>10}{:>10}".format("------", "-------", "--------", "-------", "--------"))
    for bucket in ("high", "mid", "low"):
        b = report.get(bucket, {})
        count = b.get("count", 0)
        wo = b.get("with_outcome", 0)
        avg = b.get("avg_pnl_usd", 0.0)
        wr = b.get("win_rate", 0.0)
        if avg >= 0:
            avg_str = f"+${avg:.2f}"
        else:
            avg_str = f"-${abs(avg):.2f}"
        wr_str = f"{wr * 100:.1f}%"
        print(f"{bucket.capitalize():<10}{count:>8}{wo:>10}{avg_str:>10}{wr_str:>10}")

    high_avg = report.get("high", {}).get("avg_pnl_usd", 0.0)
    low_avg = report.get("low", {}).get("avg_pnl_usd", 0.0)
    if high_avg > low_avg:
        print("\nPrimary metric: High confidence signals outperforming Low \u2713")
    else:
        print("\nPrimary metric: High confidence NOT outperforming Low \u2717")

    # ── Benchmark comparison table ─────────────────────────────────────────
    if bm_report:
        print()
        print("Benchmark Comparison (system vs each benchmark)")
        print("================================================")
        print("{:<28}{:>8}{:>12}{:>12}{:>10}".format("Benchmark", "Trades", "Sys Avg P&L", "BM Avg P&L", "Edge"))
        print("{:<28}{:>8}{:>12}{:>12}{:>10}".format("---------", "------", "-----------", "----------", "----"))
        for bm_name, bdata in sorted(bm_report.items()):
            n = bdata.get("count", 0)
            sys_avg = bdata.get("system_avg_pnl", 0.0)
            bm_avg = bdata.get("benchmark_avg_pnl", 0.0)
            edge = sys_avg - bm_avg
            sys_str = f"+${sys_avg:.2f}" if sys_avg >= 0 else f"-${abs(sys_avg):.2f}"
            bm_str = f"+${bm_avg:.2f}" if bm_avg >= 0 else f"-${abs(bm_avg):.2f}"
            edge_str = f"+${edge:.2f}" if edge >= 0 else f"-${abs(edge):.2f}"
            # Short benchmark name for display
            short_name = bm_name.replace("benchmark.", "")
            print(f"{short_name:<28}{n:>8}{sys_str:>12}{bm_str:>12}{edge_str:>10}")
    else:
        print()
        print("No benchmark comparison data yet.")
        print("Benchmarks will be recorded the next time positions close.")

    print()
    return 0


def _benchmark_comparison(db: Any) -> dict:
    """Aggregate benchmark comparison rows from signal_stratification."""
    try:
        rows = db.fetchall(
            """SELECT benchmark_name, system_pnl, benchmark_pnl
               FROM signal_stratification
               WHERE benchmark_name IS NOT NULL
                 AND system_pnl IS NOT NULL
                 AND benchmark_pnl IS NOT NULL"""
        )
    except Exception:
        return {}

    if not rows:
        return {}

    from collections import defaultdict

    buckets: dict = defaultdict(lambda: {"count": 0, "sys_total": 0.0, "bm_total": 0.0})
    for row in rows:
        bm_name = str(row["benchmark_name"])
        sys_pnl = float(row["system_pnl"])
        bm_pnl = float(row["benchmark_pnl"])
        buckets[bm_name]["count"] += 1
        buckets[bm_name]["sys_total"] += sys_pnl
        buckets[bm_name]["bm_total"] += bm_pnl

    result = {}
    for bm_name, data in buckets.items():
        n = data["count"]
        result[bm_name] = {
            "count": n,
            "system_avg_pnl": round(data["sys_total"] / n, 4) if n > 0 else 0.0,
            "benchmark_avg_pnl": round(data["bm_total"] / n, 4) if n > 0 else 0.0,
        }
    return result


def _report_cockpit(ctx: Any, args: argparse.Namespace) -> int:
    db = ctx.db
    now = datetime.now(tz=UTC)
    week_ago = (now - timedelta(days=7)).isoformat()

    trades = db.fetchone("SELECT COUNT(*) as c FROM positions WHERE opened_at >= ?", (week_ago,))
    trade_count = int(trades["c"]) if trades else 0

    pnl_row = db.fetchone(
        "SELECT COALESCE(SUM(realized_pnl), 0) as total FROM positions WHERE status = 'closed' AND closed_at >= ?",
        (week_ago,),
    )
    realized = float(pnl_row["total"]) if pnl_row else 0.0

    ks_row = db.fetchone(
        "SELECT COUNT(*) as c FROM events WHERE type = 'brain.kill_switch.v1' AND ts >= ?",
        (week_ago,),
    )
    ks_count = int(ks_row["c"]) if ks_row else 0

    hi_row = db.fetchone(
        "SELECT COUNT(*) as c FROM signal_stratification WHERE bucket = 'high' AND created_at >= ?",
        (week_ago,),
    )
    hi_count = int(hi_row["c"]) if hi_row else 0

    if getattr(args, "json", False):
        import json

        print(
            json.dumps(
                {
                    "paper_trades": trade_count,
                    "realized_pnl_usd": realized,
                    "kill_switch_triggers": ks_count,
                    "high_conviction_signals": hi_count,
                },
                indent=2,
            )
        )
        return 0

    print()
    print("7-Day Cockpit Summary")
    print("=====================")
    print("Paper trades:            " + str(trade_count))
    print(f"Realized P&L:            ${realized:.2f}")
    print("Kill switch triggers:    " + str(ks_count))
    print("High conviction signals: " + str(hi_count))
    print()
    return 0
