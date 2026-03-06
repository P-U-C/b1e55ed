"""
Prospect scoring for b1e55ed producer recruitment.

Three dimensions as specified in task 991ae6ca:
  1. Technical Depth         — infra/engineering/backend/smart-contract evidence
  2. Forecasting Potential   — quant/ML/market-analysis/signal-generation evidence
  3. Operational Reliability — task cadence, reward consistency, alignment quality
"""

TECH_KEYWORDS = [
    "infrastructure",
    "devops",
    "backend",
    "engineering",
    "smart contract",
    "blockchain",
    "solidity",
    "rust",
    "python",
    "go",
    "typescript",
    "node",
    "kubernetes",
    "docker",
    "cloud",
    "aws",
    "database",
    "api",
    "protocol",
    "security",
    "cryptography",
    "zk",
    "layer2",
    "evm",
    "validator",
    "rpc",
]

FORECAST_KEYWORDS = [
    "quant",
    "quantitative",
    "machine learning",
    "ml",
    "statistics",
    "statistical",
    "market analysis",
    "trading",
    "signal",
    "forecasting",
    "data science",
    "analytics",
    "on-chain",
    "onchain",
    "backtesting",
    "risk management",
    "portfolio",
    "financial modeling",
    "econometrics",
    "time series",
    "alpha",
    "macro",
    "research",
    "modeling",
    "prediction",
    "probability",
]

ROLES = {
    (4, 4): "Signal Producer + Data Pipeline",
    (4, 3): "Signal Producer",
    (3, 4): "Quantitative Contributor",
    (4, 2): "Infrastructure Producer",
    (3, 3): "General Contributor",
    (2, 4): "Market Analyst / Signal Source",
    (2, 3): "Junior Contributor",
    (1, 4): "Forecasting Specialist",
}


def _kw_hit_count(text: str, keywords: list) -> int:
    t = text.lower()
    return sum(1 for kw in keywords if kw in t)


def _score_prospect(p) -> dict:
    """Score a single prospect across the three dimensions."""
    # Build searchable text from all capabilities/knowledge
    cap_text = " ".join(p.postfiat_capabilities or []).lower()
    summary_text = (getattr(p, "_pf_summary", "") or "").lower()
    all_text = cap_text + " " + summary_text

    # ── Signals ───────────────────────────────────────────────────────────────
    alignment = getattr(p, "_pf_alignment", 0) or 0
    alignment_tier = (getattr(p, "_pf_alignment_tier", "") or "").lower()
    sybil_score = getattr(p, "_pf_sybil", 0) or 0
    sybil_risk = (getattr(p, "_pf_sybil_risk", "") or "").lower()
    monthly_pft = p.postfiat_pft_earned or 0
    weekly_pft = getattr(p, "_pf_weekly_rewards", 0) or 0
    monthly_tasks = p.postfiat_task_count or 0
    lb_month = getattr(p, "_pf_lb_month", 0) or 0
    getattr(p, "_pf_lb_week", 0) or 0

    tech_hits = _kw_hit_count(all_text, TECH_KEYWORDS)
    forecast_hits = _kw_hit_count(all_text, FORECAST_KEYWORDS)
    cap_count = len(p.postfiat_capabilities or [])

    # ── 1. Technical Depth (1–5) ──────────────────────────────────────────────
    tech = 1
    if tech_hits >= 5:
        tech = 5
    elif tech_hits >= 3:
        tech = 4
    elif tech_hits >= 2:
        tech = 3
    elif tech_hits >= 1:
        tech = 2

    # Sybil score boosts (strong identity = real technical contributor)
    if sybil_score >= 85 and tech < 5:
        tech = min(5, tech + 1)

    # Cap count signal (many capabilities = breadth)
    if cap_count >= 10 and tech < 4:
        tech = min(4, tech + 1)

    tech_evidence_parts = []
    if tech_hits > 0:
        matched = [kw for kw in TECH_KEYWORDS if kw in all_text][:5]
        tech_evidence_parts.append(f"Technical keyword matches: {', '.join(matched)}")
    if sybil_score > 0:
        tech_evidence_parts.append(f"Sybil score {sybil_score} ({sybil_risk} risk)")
    if cap_count > 0:
        tech_evidence_parts.append(f"{cap_count} declared capabilities")
    tech_evidence = ". ".join(tech_evidence_parts) or "No technical signals detected in declared capabilities."
    if not tech_evidence_parts:
        tech = 1

    # ── 2. Forecasting / Quantitative Potential (1–5) ─────────────────────────
    forecast = 1
    if forecast_hits >= 4:
        forecast = 5
    elif forecast_hits >= 3:
        forecast = 4
    elif forecast_hits >= 2:
        forecast = 3
    elif forecast_hits >= 1:
        forecast = 2

    # High alignment boosts forecasting (quality output = calibrated thinking)
    if alignment >= 90 and forecast < 5:
        forecast = min(5, forecast + 1)
    elif alignment >= 75 and forecast < 4:
        forecast = min(4, forecast + 1)

    # High monthly PFT = consistent output quality
    if monthly_pft > 500_000 and forecast < 4:
        forecast = min(4, forecast + 1)

    forecast_evidence_parts = []
    if forecast_hits > 0:
        matched = [kw for kw in FORECAST_KEYWORDS if kw in all_text][:5]
        forecast_evidence_parts.append(f"Quantitative keyword matches: {', '.join(matched)}")
    if alignment > 0:
        forecast_evidence_parts.append(f"Alignment score {alignment} ({alignment_tier})")
    if monthly_pft > 0:
        forecast_evidence_parts.append(f"Monthly PFT output {monthly_pft:,.0f}")
    forecast_evidence = ". ".join(forecast_evidence_parts) or "No forecasting signals detected."
    if not forecast_evidence_parts:
        forecast = 1

    # ── 3. Operational Reliability (1–5) ──────────────────────────────────────
    reliability = 1

    # Leaderboard month score is the cleanest signal (composite of consistency + output)
    if lb_month >= 80:
        reliability = 5
    elif lb_month >= 60:
        reliability = 4
    elif lb_month >= 40:
        reliability = 3
    elif lb_month >= 15:
        reliability = 2

    # Weekly/monthly ratio — consistent weekly cadence vs bursty monthly
    if monthly_pft > 0 and weekly_pft > 0:
        weekly_ratio = weekly_pft / monthly_pft
        if 0.2 <= weekly_ratio <= 0.35 and reliability < 5:  # ~25% each week = consistent
            reliability = min(5, reliability + 1)

    # Monthly task count
    if monthly_tasks >= 30 and reliability < 5:
        reliability = min(5, reliability + 1)
    elif monthly_tasks >= 10 and reliability < 4:
        reliability = min(4, reliability + 1)

    reliability_evidence_parts = []
    if lb_month > 0:
        reliability_evidence_parts.append(f"Leaderboard month score: {lb_month}")
    if monthly_tasks > 0:
        reliability_evidence_parts.append(f"{monthly_tasks} tasks/month")
    if monthly_pft > 0:
        reliability_evidence_parts.append(f"{monthly_pft:,.0f} PFT/month")
    if weekly_pft > 0:
        weekly_ratio = weekly_pft / monthly_pft if monthly_pft > 0 else 0
        reliability_evidence_parts.append(f"weekly/monthly ratio: {weekly_ratio:.0%}")
    reliability_evidence = ". ".join(reliability_evidence_parts) or "Insufficient activity data."

    # ── Composite & Role ──────────────────────────────────────────────────────
    composite = tech + forecast + reliability

    # Role lookup (best matching key)
    role_key = (min(tech, 4), min(forecast, 4))
    role = ROLES.get(role_key) or ROLES.get((min(tech, 4), min(forecast, 3))) or "General Network Participant"

    # Priority
    if composite >= 12:
        priority = "🔴 NOW"
    elif composite >= 9:
        priority = "🟡 AT-GATE"
    elif composite >= 6:
        priority = "⚪ SPECULATIVE"
    else:
        priority = "⚪ SPECULATIVE"

    # Assessment (2-3 sentences)
    assessment = _build_assessment(p, tech, forecast, reliability, composite, all_text)
    gaps = _build_gaps(tech, forecast, reliability, cap_count, monthly_tasks, sybil_score)
    top3_rationale = _build_top3_rationale(p, tech, forecast, reliability, all_text)

    return {
        "wallet": p.handle,
        "summary": getattr(p, "_pf_summary", "") or p.display_name or p.handle[:20],
        "tech_depth": tech,
        "forecasting": forecast,
        "reliability": reliability,
        "composite": composite,
        "role": role,
        "priority": priority,
        "tech_evidence": tech_evidence,
        "forecast_evidence": forecast_evidence,
        "reliability_evidence": reliability_evidence,
        "assessment": assessment,
        "gaps": gaps,
        "top3_rationale": top3_rationale,
        # raw signals for sorting
        "_alignment": alignment,
        "_monthly_pft": monthly_pft,
        "_lb_month": lb_month,
    }


def _build_assessment(p, tech, forecast, reliability, composite, all_text) -> str:
    summary = getattr(p, "_pf_summary", "") or ""
    monthly_pft = p.postfiat_pft_earned or 0
    alignment = getattr(p, "_pf_alignment", 0) or 0

    tech_adj = {
        5: "strong technical background",
        4: "solid technical capabilities",
        3: "moderate technical presence",
        2: "emerging technical skills",
        1: "limited technical signals",
    }[tech]
    forecast_adj = {
        5: "clear quantitative/forecasting expertise",
        4: "good forecasting orientation",
        3: "some analytical capability",
        2: "early-stage analytical signals",
        1: "limited forecasting signals",
    }[forecast]
    rel_adj = {5: "highly consistent contributor", 4: "reliable contributor", 3: "reasonably active", 2: "intermittently active", 1: "activity data sparse"}[
        reliability
    ]

    role_fit = ""
    if tech >= 4 and forecast >= 4:
        role_fit = "Strong candidate for both signal generation and infrastructure producer roles."
    elif forecast >= 4:
        role_fit = "Best fit as a signal producer or market analyst feeding the b1e55ed synthesis engine."
    elif tech >= 4:
        role_fit = "Best fit for data pipeline or infrastructure producer roles rather than signal generation."
    else:
        role_fit = "Speculative candidate — would need more demonstrated output before activation."

    return f"{summary} shows {tech_adj} and {forecast_adj}, with a {rel_adj} track record ({monthly_pft:,.0f} PFT/month, alignment {alignment}). {role_fit}"


def _build_gaps(tech, forecast, reliability, cap_count, monthly_tasks, sybil_score) -> str:
    gaps = []
    if tech <= 2:
        gaps.append("no observable technical capability signals — need GitHub/portfolio review")
    if forecast <= 2:
        gaps.append("no quantitative or market analysis signals — profile review required before outreach")
    if reliability <= 2:
        gaps.append("low task cadence — unclear if contributor is still active")
    if sybil_score == 0:
        gaps.append("sybil score unavailable — identity verification strength unknown")
    if cap_count == 0:
        gaps.append("no declared capabilities — profile may be incomplete")
    return ". ".join(gaps) if gaps else "No significant gaps identified — profile data sufficient for initial assessment."


def _build_top3_rationale(p, tech, forecast, reliability, all_text) -> str:
    getattr(p, "_pf_summary", "") or p.handle[:20]
    dims = []
    if tech >= 4:
        dims.append("technical depth")
    if forecast >= 4:
        dims.append("forecasting capability")
    if reliability >= 4:
        dims.append("operational consistency")
    dim_str = " + ".join(dims) if dims else "balanced scores across all dimensions"
    return f"Top-ranked on {dim_str}; ready for b1e55ed producer activation at the 500-outcome gate."


def score_for_submission(prospects: list) -> list:
    """Score all prospects and return sorted list of dicts, highest composite first."""
    scored = [_score_prospect(p) for p in prospects]
    # Sort: composite desc, then alignment desc as tiebreaker
    scored.sort(key=lambda x: (x["composite"], x["_alignment"]), reverse=True)
    return scored
