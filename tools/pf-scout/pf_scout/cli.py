#!/usr/bin/env python3
"""pf-scout CLI — Post Fiat network intelligence tool."""

import argparse
import os
import sys

from .collectors.postfiat import (
    collect_leaderboard,
    collect_my_contacts,
    get_network_summary,
)
from .config import load_token, save_token
from .output.markdown import generate_report, network_table
from .scoring.scorer import load_rubric, score_all


def _require_token():
    token = load_token()
    if not token:
        print("No JWT token configured. Run `pf-scout setup` or set PF_JWT_TOKEN env var.")
        sys.exit(1)
    return token


def cmd_setup(args):
    """Interactive setup wizard."""
    print("=" * 60)
    print("  pf-scout setup")
    print("=" * 60)
    print()
    print("You need a JWT token from tasknode.postfiat.org.")
    print()
    print("How to get it:")
    print("  1. Go to https://tasknode.postfiat.org and log in (GitHub OAuth)")
    print("  2. Open browser DevTools (F12 or Cmd+Opt+I)")
    print("  3. Go to Network tab")
    print("  4. Click any page/action that triggers an API call")
    print("  5. Find a request to /api/... and click it")
    print("  6. In Headers, find 'Authorization: Bearer <token>'")
    print("  7. Copy everything after 'Bearer '")
    print()
    token = input("Paste your Post Fiat JWT token: ").strip()
    if not token:
        print("No token provided. Aborting.")
        sys.exit(1)

    # Validate
    print("\nValidating token...")
    os.environ["PF_JWT_TOKEN"] = token
    summary = get_network_summary(jwt_token=token)
    if not summary:
        print("❌ Token validation failed. Could not reach /api/leaderboard.")
        print("   Check that the token is correct and not expired.")
        sys.exit(1)

    save_token(token)
    print("✅ Token saved to ~/.pf-scout/config.json")
    print()
    _print_summary(summary)


def _print_summary(summary):
    print("📊 Post Fiat Network Summary")
    print(f"   Active contributors: {summary.get('active_contributors', '?')}")
    print(f"   Monthly PFT output:  {summary.get('monthly_pft', 0):,.0f}")
    print(f"   Monthly tasks:       {summary.get('monthly_tasks', 0):,}")
    print(f"   Weekly PFT output:   {summary.get('weekly_pft', 0):,.0f}")
    tv = summary.get("top_by_volume", {})
    ta = summary.get("top_by_alignment", {})
    if tv.get("summary"):
        print(f"   Top by volume:       {tv['summary']} ({tv.get('monthly_pft', 0):,.0f} PFT)")
    if ta.get("summary"):
        print(f"   Top by alignment:    {ta['summary']} (score: {ta.get('alignment_score', 0)})")


def cmd_network_summary(args):
    token = _require_token()
    summary = get_network_summary(jwt_token=token)
    if not summary:
        print("Failed to fetch network summary.")
        sys.exit(1)
    _print_summary(summary)


def cmd_network_top(args):
    token = _require_token()
    prospects = collect_leaderboard(jwt_token=token, require_capabilities=False)
    if not prospects:
        print("No leaderboard data.")
        sys.exit(1)

    sort_key = {
        "month": "_pf_lb_month",
        "week": "_pf_lb_week",
        "volume": "postfiat_pft_earned",
        "alignment": "_pf_alignment",
    }.get(args.by, "_pf_lb_month")

    prospects.sort(key=lambda p: getattr(p, sort_key, 0) or 0, reverse=True)
    top = prospects[: args.count]

    print(f"\n🏆 Top {len(top)} by {args.by}\n")
    print("| Rank | Summary | Monthly PFT | Alignment | Sybil Risk |")
    print("|------|---------|-------------|-----------|------------|")
    for i, p in enumerate(top, 1):
        summary = getattr(p, "_pf_summary", p.display_name or p.handle)[:40]
        monthly = p.postfiat_pft_earned
        alignment = getattr(p, "_pf_alignment", 0)
        sybil = getattr(p, "_pf_sybil_risk", "?")
        print(f"| {i} | {summary} | {monthly:,.0f} | {alignment} | {sybil} |")
    print()


def cmd_network_discover(args):
    token = _require_token()

    # Fetch and filter
    prospects = collect_leaderboard(
        jwt_token=token,
        min_alignment=args.min_alignment,
        min_monthly_pft=args.min_monthly_pft,
        require_capabilities=True,
    )
    if not prospects:
        print("No prospects match filters.")
        sys.exit(1)

    # Domain filter
    if args.domain:
        kw = args.domain.lower()
        prospects = [p for p in prospects if any(kw in c.lower() for c in p.postfiat_capabilities)]
        if not prospects:
            print(f"No prospects match domain filter '{args.domain}'.")
            sys.exit(1)

    # Score
    rubric_path = args.rubric or _default_rubric()
    rubric = load_rubric(rubric_path)
    scored = score_all(prospects, rubric)

    # Summary header
    summary = get_network_summary(jwt_token=token)
    if summary:
        _print_summary(summary)
        print()

    # Output
    md = network_table(scored, title="Network Discovery")
    print(md)

    if args.output:
        with open(args.output, "w") as f:
            f.write(md)
        print(f"\nSaved to {args.output}")


def cmd_network_prospect(args):
    """
    Build a submission-ready b1e55ed producer prospect document from the PF leaderboard.

    Scores all contributors on:
      1. Technical Depth
      2. Forecasting / Quantitative Potential
      3. Operational Reliability

    Output: a markdown file ready to upload as task evidence.
    """
    token = _require_token()

    print("Fetching Post Fiat leaderboard...")
    prospects = collect_leaderboard(
        jwt_token=token,
        min_alignment=args.min_alignment,
        require_capabilities=False,  # include everyone; scorer handles it
    )
    if not prospects:
        print("No leaderboard data.")
        sys.exit(1)

    # Filter to those with any signal at all
    active = [p for p in prospects if p.postfiat_pft_earned > 0 or p.postfiat_task_count > 0]
    print(f"Scoring {len(active)} active contributors...")

    from .output.markdown import generate_prospect_report

    md = generate_prospect_report(active)

    out = args.output or "b1e55ed-prospect-pipeline.md"
    with open(out, "w") as f:
        f.write(md)

    # Quick stats
    from .output.prospect_scorer import score_for_submission

    scored = score_for_submission(active)
    high = sum(1 for p in scored if p["composite"] >= 11)
    mid = sum(1 for p in scored if 7 <= p["composite"] < 11)
    spec = sum(1 for p in scored if p["composite"] < 7)

    print(f"\n✅ Prospect pipeline written to {out}")
    print(f"   Total scored:    {len(scored)}")
    print(f"   🔴 High priority: {high}")
    print(f"   🟡 Mid priority:  {mid}")
    print(f"   ⚪ Speculative:   {spec}")
    print("\nTop 3:")
    for i, p in enumerate(scored[:3], 1):
        print(f"  {i}. {p['summary'][:45]} — Composite {p['composite']}/15 ({p['priority']})")
    print(f"\nUpload {out} to tasknode.postfiat.org to submit.")


def cmd_network_contacts(args):
    token = _require_token()
    contacts = collect_my_contacts(jwt_token=token)
    if not contacts:
        print("No contacts found (or API returned empty).")
        sys.exit(1)

    print(f"\n📇 Your Contacts ({len(contacts)})\n")
    print("| Wallet | Summary | Alignment | Sybil | Monthly PFT | Last Message |")
    print("|--------|---------|-----------|-------|-------------|--------------|")
    for p in contacts:
        wallet = p.handle[:8] + "..." + p.handle[-4:] if len(p.handle) > 16 else p.handle
        summary = getattr(p, "_pf_summary", p.display_name or "")[:35]
        alignment = getattr(p, "_pf_alignment", 0)
        sybil = getattr(p, "_pf_sybil_risk", "?")
        monthly = p.postfiat_pft_earned
        last_msg = (getattr(p, "_pf_last_message_at", "") or "")[:10]
        print(f"| {wallet} | {summary} | {alignment} | {sybil} | {monthly:,.0f} | {last_msg} |")
    print()


def cmd_score(args):
    from .collectors.manual import load_csv

    prospects = load_csv(args.input)
    rubric = load_rubric(args.rubric or _default_rubric())
    scored = score_all(prospects, rubric)
    md = generate_report(scored, rubric)
    if args.output:
        with open(args.output, "w") as f:
            f.write(md)
        print(f"Report written to {args.output}")
    else:
        print(md)


def cmd_report(args):
    """Run generate_report.py logic."""
    from .collectors.manual import load_csv

    input_csv = args.input or "examples/b1e55ed-prospects-input.csv"
    rubric_path = args.rubric or _default_rubric()

    prospects = load_csv(input_csv)
    rubric = load_rubric(rubric_path)
    scored = score_all(prospects, rubric)
    md = generate_report(scored, rubric, title="b1e55ed Producer Recruitment — Scored Prospect List")
    out = args.output or "b1e55ed-prospect-list.md"
    with open(out, "w") as f:
        f.write(md)
    print(f"Report written to {out} ({len(md)} chars)")


def _default_rubric():
    """Find default rubric relative to package."""
    candidates = [
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "rubrics", "b1e55ed.yaml"),
        "rubrics/b1e55ed.yaml",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return "rubrics/b1e55ed.yaml"


def main():
    parser = argparse.ArgumentParser(
        prog="pf-scout",
        description="Post Fiat network intelligence — discover contributors, build contacts, recruit producers.",
    )
    sub = parser.add_subparsers(dest="command")

    # setup
    sub.add_parser("setup", help="Interactive setup wizard (configure JWT token)")

    # network
    net = sub.add_parser("network", help="Network commands (discover, contacts, top, summary)")
    net_sub = net.add_subparsers(dest="network_command")

    # network summary
    net_sub.add_parser("summary", help="Print network summary stats")

    # network top
    top_p = net_sub.add_parser("top", help="Top contributors by score")
    top_p.add_argument("--by", choices=["volume", "alignment", "week", "month"], default="month")
    top_p.add_argument("--count", type=int, default=10)

    # network discover
    disc_p = net_sub.add_parser("discover", help="Discover and score prospects from leaderboard")
    disc_p.add_argument("--min-alignment", type=int, default=60)
    disc_p.add_argument("--min-monthly-pft", type=float, default=0)
    disc_p.add_argument("--domain", type=str, default=None, help="Filter by capability keyword")
    disc_p.add_argument("--rubric", type=str, default=None)
    disc_p.add_argument("--output", type=str, default=None)

    # network prospect
    prospect_p = net_sub.add_parser("prospect", help="Build scored b1e55ed producer prospect document")
    prospect_p.add_argument("--min-alignment", type=int, default=0, help="Minimum alignment score filter (default: 0 = all)")
    prospect_p.add_argument("--output", type=str, default=None, help="Output file (default: b1e55ed-prospect-pipeline.md)")

    # network contacts
    net_sub.add_parser("contacts", help="Show your enriched contact list")

    # score
    score_p = sub.add_parser("score", help="Score prospects from CSV")
    score_p.add_argument("--input", required=True, help="Input CSV file")
    score_p.add_argument("--rubric", default=None)
    score_p.add_argument("--output", default=None)

    # report
    report_p = sub.add_parser("report", help="Generate full b1e55ed prospect report")
    report_p.add_argument("--input", default=None)
    report_p.add_argument("--rubric", default=None)
    report_p.add_argument("--output", default=None)

    args = parser.parse_args()

    if args.command == "setup":
        cmd_setup(args)
    elif args.command == "network":
        nc = getattr(args, "network_command", None)
        if nc == "summary":
            cmd_network_summary(args)
        elif nc == "top":
            cmd_network_top(args)
        elif nc == "discover":
            cmd_network_discover(args)
        elif nc == "prospect":
            cmd_network_prospect(args)
        elif nc == "contacts":
            cmd_network_contacts(args)
        else:
            print("Usage: pf-scout network {summary|top|discover|contacts}")
            sys.exit(1)
    elif args.command == "score":
        cmd_score(args)
    elif args.command == "report":
        cmd_report(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
