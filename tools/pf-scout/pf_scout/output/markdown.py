"""Markdown report generator for pf-scout."""

from datetime import datetime

from ..collectors.base import Prospect


def generate_prospect_report(prospects: list, title: str = "b1e55ed Producer Prospect Pipeline") -> str:
    """
    Generate a submission-ready markdown document for the b1e55ed producer prospect task.

    Scores on three dimensions:
      1. Technical Depth (1-5)
      2. Forecasting / Quantitative Potential (1-5)
      3. Operational Reliability (1-5)
    """
    from .prospect_scorer import score_for_submission

    scored = score_for_submission(prospects)
    top3 = scored[:3]
    date_str = datetime.utcnow().strftime("%Y-%m-%d")

    lines = []

    # ── Executive Summary ─────────────────────────────────────────────────────
    lines += [
        f"# {title}",
        "",
        f"*Generated {date_str} by pf-scout from Post Fiat leaderboard data*",
        "",
        "---",
        "",
        "## Executive Summary",
        "",
        f"This pipeline document scores **{len(scored)} Post Fiat network contributors** on their "
        "fit as potential b1e55ed signal producers or contributors. Contributors were assessed "
        "across three dimensions — Technical Depth, Forecasting/Quantitative Potential, and "
        "Operational Reliability — using observable signals from the Post Fiat leaderboard: "
        "declared capabilities, expert knowledge domains, monthly task volume, PFT reward "
        "consistency, alignment scores, and sybil risk ratings.",
        "",
        "**Score distribution:**",
    ]

    high = [p for p in scored if p["composite"] >= 11]
    mid = [p for p in scored if 7 <= p["composite"] < 11]
    spec = [p for p in scored if p["composite"] < 7]
    lines += [
        f"- 🔴 High priority (composite ≥11): {len(high)} prospects",
        f"- 🟡 Mid priority (composite 7–10): {len(mid)} prospects",
        f"- ⚪ Speculative (<7): {len(spec)} prospects",
        "",
        "**Top 3 prospects:**",
        "",
    ]
    for i, p in enumerate(top3, 1):
        lines.append(f"{i}. **{p['summary']}** (`{p['wallet'][:10]}...`) — Composite {p['composite']}/15. {p['top3_rationale']}")
    lines += [
        "",
        "**Activation trigger:** Outreach pipeline activates when b1e55ed reaches the "
        "**500-outcome meta-producer gate**. This document is pre-activation intelligence "
        "only — no outreach should occur before gate confirmation.",
        "",
        "---",
        "",
    ]

    # ── Scoring Rubric ────────────────────────────────────────────────────────
    lines += [
        "## Scoring Rubric",
        "",
        "| Dimension | Scale | Signal Sources |",
        "|-----------|-------|----------------|",
        "| **Technical Depth** | 1–5 | Capabilities tags (infra, engineering, backend, devops, "
        "smart contracts), expert knowledge domains, sybil score (identity verification strength) |",
        "| **Forecasting / Quantitative Potential** | 1–5 | Capabilities/expertise in quant, ML, "
        "statistics, market analysis, signal generation, data pipelines, on-chain analytics |",
        "| **Operational Reliability** | 1–5 | Monthly task count, PFT reward consistency (monthly vs weekly ratio), leaderboard month score, alignment tier |",
        "",
        "**Composite** = sum of three dimensions (max 15). Activation Priority based on composite.",
        "",
        "---",
        "",
    ]

    # ── Scored Table ──────────────────────────────────────────────────────────
    lines += [
        "## Scored Prospect Table",
        "",
        "| # | Contributor | Wallet | Tech Depth | Forecasting | Op Reliability | Composite | Role | Priority |",
        "|---|-------------|--------|-----------|-------------|----------------|-----------|------|----------|",
    ]
    for i, p in enumerate(scored, 1):
        wallet_short = p["wallet"][:10] + "..." if len(p["wallet"]) > 14 else p["wallet"]
        lines.append(
            f"| {i} | {p['summary'][:38]} | `{wallet_short}` | "
            f"{p['tech_depth']}/5 | {p['forecasting']}/5 | {p['reliability']}/5 | "
            f"**{p['composite']}/15** | {p['role']} | {p['priority']} |"
        )
    lines += ["", "---", ""]

    # ── Per-Prospect Detail ───────────────────────────────────────────────────
    lines += ["## Prospect Assessments", ""]
    for i, p in enumerate(scored, 1):
        lines += [
            f"### {i}. {p['summary']}",
            f"**Wallet:** `{p['wallet']}`  ",
            f"**Composite:** {p['composite']}/15 | Tech {p['tech_depth']} · Forecast {p['forecasting']} · Reliability {p['reliability']}  ",
            f"**Suggested Role:** {p['role']}  ",
            f"**Activation Priority:** {p['priority']}",
            "",
            f"**Technical Depth ({p['tech_depth']}/5):** {p['tech_evidence']}",
            "",
            f"**Forecasting Potential ({p['forecasting']}/5):** {p['forecast_evidence']}",
            "",
            f"**Operational Reliability ({p['reliability']}/5):** {p['reliability_evidence']}",
            "",
            f"**Assessment:** {p['assessment']}",
            "",
            f"**Gaps:** {p['gaps']}",
            "",
            "---",
            "",
        ]

    return "\n".join(lines)


def network_table(prospects, title="Post Fiat Network", show_fields=None) -> str:
    """Generate a markdown table for network discovery results."""
    lines = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"{len(prospects)} prospects scored")
    lines.append("")
    lines.append("| Rank | Summary | Wallet | Alignment | Sybil | Monthly PFT | Monthly Tasks | Tier |")
    lines.append("|------|---------|--------|-----------|-------|-------------|---------------|------|")
    for i, p in enumerate(prospects, 1):
        wallet = p.handle[:8] + "..." + p.handle[-4:] if len(p.handle) > 16 else p.handle
        summary = getattr(p, "_pf_summary", p.display_name or p.handle)[:40]
        alignment = getattr(p, "_pf_alignment", 0)
        sybil = getattr(p, "_pf_sybil_risk", "?")
        monthly_pft = p.postfiat_pft_earned
        monthly_tasks = p.postfiat_task_count
        tier = p.tier
        lines.append(f"| {i} | {summary} | {wallet} | {alignment} | {sybil} | {monthly_pft:,.0f} | {monthly_tasks} | {tier} |")
    lines.append("")
    return "\n".join(lines)


def generate_report(prospects: list[Prospect], rubric: dict, title: str = "Prospect List") -> str:
    dimensions = rubric.get("dimensions", [])
    dim_ids = [d["id"] for d in dimensions]
    dim_names = {d["id"]: d["name"] for d in dimensions}

    lines = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"Generated by **pf-scout** | {len(prospects)} prospects scored")
    lines.append("")

    # Rubric summary
    lines.append("## Scoring Rubric")
    lines.append("")
    lines.append("| Dimension | Weight | Description |")
    lines.append("|-----------|--------|-------------|")
    for d in dimensions:
        lines.append(f"| {d['name']} | {d.get('weight', 1.0):.1f}× | {d.get('description', '')} |")
    lines.append("")
    lines.append("**Scale**: 1–5 per dimension. Weighted score = Σ(score × weight).")
    lines.append("**Tiers**: TOP ≥70th pct raw · MID 40–70th pct · SPECULATIVE <40th pct")
    lines.append("")

    # Main table
    lines.append("## Prospect Scores")
    lines.append("")

    header_cols = ["Handle", "Display Name"] + [dim_names[d] for d in dim_ids] + ["Raw", "Weighted", "Tier"]
    lines.append("| " + " | ".join(header_cols) + " |")
    lines.append("| " + " | ".join(["---"] * len(header_cols)) + " |")

    for p in prospects:
        dim_scores = [str(p.dimension_scores.get(d, "—")) for d in dim_ids]
        row = [
            f"`{p.handle}`",
            p.display_name or p.handle,
            *dim_scores,
            str(p.total_score),
            f"{p.weighted_score:.1f}",
            p.tier,
        ]
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")

    # Evidence notes per prospect
    lines.append("## Evidence Notes")
    lines.append("")
    for p in prospects:
        lines.append(f"### `{p.handle}` — {p.display_name or ''}")
        lines.append("")
        if p.notes:
            lines.append(f"**Notes**: {p.notes}")
            lines.append("")
        for dim_id in dim_ids:
            score = p.dimension_scores.get(dim_id, "—")
            evidence = p.dimension_evidence.get(dim_id, "")
            lines.append(f"- **{dim_names[dim_id]}** ({score}/5): {evidence}")
        lines.append("")

    # Top-tier recruitment angles
    top_prospects = [p for p in prospects if p.tier == "🔴 TOP"]
    if top_prospects:
        lines.append("## Top-Tier Recruitment Angles")
        lines.append("")
        for p in top_prospects:
            lines.append(f"### `{p.handle}` — {p.display_name or ''}")
            if p.recruitment_angle:
                lines.append(p.recruitment_angle)
            else:
                lines.append("*(Recruitment angle not set — populate via `--angles` or manual edit)*")
            lines.append("")

    return "\n".join(lines)
