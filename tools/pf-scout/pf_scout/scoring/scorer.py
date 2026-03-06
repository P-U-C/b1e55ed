"""Rubric-based scorer for pf-scout prospects."""

import yaml

from ..collectors.base import Prospect


def load_rubric(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _pf_val(prospect: Prospect, attr: str, default=0):
    """Safely read a tasknode API field stashed on the prospect object."""
    return getattr(prospect, attr, default) or default


def _auto_score(prospect: Prospect, dim_id: str) -> tuple[int, str]:
    """
    Auto-score a dimension based on available signals.
    Returns (score, evidence_note).
    Override by setting prospect.manual_scores[dim_id].
    """
    gh_commits = sum(prospect.github_contributions.values())
    gh_bio = (prospect.github_bio or "").lower()
    gh_company = (prospect.github_company or "").lower()

    # Tasknode API signals (available when source="postfiat" via JWT)
    pf_alignment = _pf_val(prospect, "_pf_alignment")
    pf_sybil = _pf_val(prospect, "_pf_sybil")
    pf_weekly = _pf_val(prospect, "_pf_weekly_rewards")
    pf_lb_month = _pf_val(prospect, "_pf_lb_month")

    quant_keywords = ["quant", "ml", "machine learning", "phd", "statistics", "data science", "algo", "systematic", "quantitative", "finance", "trading"]  # noqa: N806
    infra_keywords = ["devops", "infrastructure", "cloud", "kubernetes", "docker", "node", "validator", "server", "backend", "engineer", "sre", "platform"]  # noqa: N806
    market_keywords = ["trader", "trading", "portfolio", "macro", "alpha", "market", "analyst", "fund", "hedge", "investment", "pm ", "portfolio manager"]  # noqa: N806
    signal_keywords = ["signal", "analytics", "bigquery", "pipeline", "etl", "data", "blockchain analytics", "on-chain", "onchain", "sensor"]  # noqa: N806

    def kw_score(keywords: list[str]) -> int:
        hits = sum(1 for kw in keywords if kw in gh_bio or kw in gh_company)
        if hits >= 3:
            return 4
        if hits >= 2:
            return 3
        if hits >= 1:
            return 2
        return 1

    if dim_id == "quant_depth":
        score = kw_score(quant_keywords)
        for cap in prospect.postfiat_capabilities:
            if any(kw in cap.lower() for kw in ["quant", "model", "statistics", "ml", "financial model", "backtesting", "risk management"]):
                score = min(5, score + 1)
                break
        # High alignment from tasknode = proven output quality
        if pf_alignment >= 90:
            score = min(5, score + 1)
        evidence = f"PF capabilities match; alignment={pf_alignment}; GitHub bio: '{prospect.github_bio[:60]}'"
        return score, evidence

    elif dim_id == "infra_capability":
        score = kw_score(infra_keywords)
        if gh_commits > 500:
            score = min(5, score + 2)
        elif gh_commits > 100:
            score = min(5, score + 1)
        # Sybil score from tasknode is identity verification strength
        if pf_sybil >= 85:
            score = min(5, score + 1)
        evidence = f"{gh_commits} commits; sybil={pf_sybil}; lb_month={pf_lb_month}"
        return score, evidence

    elif dim_id == "market_analysis":
        score = kw_score(market_keywords)
        if prospect.twitter_followers > 10000:
            score = min(5, score + 1)
        # Monthly PFT output is a strong signal of market engagement
        if prospect.postfiat_pft_earned > 300_000:
            score = min(5, score + 2)
        elif prospect.postfiat_pft_earned > 100_000:
            score = min(5, score + 1)
        evidence = f"Monthly PFT: {prospect.postfiat_pft_earned:,.0f}; Twitter: {prospect.twitter_followers}"
        return score, evidence

    elif dim_id == "signal_generation":
        score = kw_score(signal_keywords)
        if prospect.postfiat_task_count > 50:
            score = min(5, score + 1)
        # Weekly output = active signal producer cadence
        if pf_weekly > 100_000:
            score = min(5, score + 1)
        evidence = f"Monthly tasks: {prospect.postfiat_task_count}; weekly PFT: {pf_weekly:,.0f}"
        return score, evidence

    elif dim_id == "engagement_consistency":
        # Leaderboard month score is directly a consistency metric
        if pf_lb_month >= 80:
            score = 5
        elif pf_lb_month >= 60:
            score = 4
        elif pf_lb_month >= 40:
            score = 3
        elif pf_lb_month >= 20:
            score = 2
        else:
            score = 1
        # GitHub commits as secondary signal
        if gh_commits > 200 and score < 5:
            score = min(5, score + 1)
        repos = list(prospect.github_contributions.keys())
        evidence = f"lb_month={pf_lb_month}; PF tasks/mo={prospect.postfiat_task_count}; git repos={len(repos)}"
        return score, evidence

    else:
        return 1, "no auto-scoring rule for this dimension"


def score_prospect(prospect: Prospect, rubric: dict) -> Prospect:
    """Apply rubric to a prospect, filling dimension_scores and weighted_score."""
    dimensions = rubric.get("dimensions", [])
    total_raw = 0
    max_raw = len(dimensions) * 5
    weighted_sum = 0.0
    sum(d.get("weight", 1.0) * 5 for d in dimensions)

    for dim in dimensions:
        dim_id = dim["id"]
        weight = dim.get("weight", 1.0)

        # Use manual override if present
        if dim_id in prospect.manual_scores:
            score = int(prospect.manual_scores[dim_id])
            evidence = prospect.notes or "manual score"
        else:
            score, evidence = _auto_score(prospect, dim_id)

        prospect.dimension_scores[dim_id] = score
        prospect.dimension_evidence[dim_id] = evidence
        total_raw += score
        weighted_sum += score * weight

    prospect.total_score = total_raw
    prospect.weighted_score = round(weighted_sum, 2)

    # Tier calculation
    rubric.get("tiers", {})
    pct = total_raw / max_raw if max_raw > 0 else 0
    if pct >= 0.64:
        prospect.tier = "🔴 TOP"
    elif pct >= 0.40:
        prospect.tier = "🟡 MID"
    else:
        prospect.tier = "⚪ SPECULATIVE"

    return prospect


def score_all(prospects: list[Prospect], rubric: dict) -> list[Prospect]:
    """Score all prospects and sort by weighted_score descending."""
    scored = [score_prospect(p, rubric) for p in prospects]
    return sorted(scored, key=lambda p: p.weighted_score, reverse=True)
