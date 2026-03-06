"""Post Fiat platform collector — tasknode JWT API.

Uses the tasknode.postfiat.org authenticated REST API instead of scraping.

Auth:
    JWT Bearer token from tasknode.postfiat.org (obtained via GitHub OAuth).
    Pass as PF_JWT_TOKEN env var, or pass jwt_token= directly.

    To get your token:
        1. Log in to tasknode.postfiat.org
        2. Open DevTools → Network → click any API request
        3. Copy the Authorization header value (everything after "Bearer ")

Legacy cookie-based auth (app.postfiat.org) is still supported as fallback.

API Endpoints used:
    GET /api/leaderboard          — all active contributors with scores + capabilities
    GET /api/tasks/summary        — your own outstanding/pending tasks
    GET /api/contacts             — your contact list with wallet addresses
"""

import json
import os
import re
import time
import urllib.error
import urllib.request

from .base import Prospect

TASKNODE_BASE = os.environ.get("PF_TASKNODE_BASE", "https://tasknode.postfiat.org")
PF_APP_BASE = os.environ.get("PF_APP_BASE", "https://app.postfiat.org")


# ── Low-level HTTP ─────────────────────────────────────────────────────────────


def _api_get(path: str, jwt_token: str) -> dict | None:
    """Authenticated GET against the tasknode API. Returns parsed JSON or None."""
    url = f"{TASKNODE_BASE}{path}"
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/json",
        "User-Agent": "pf-scout/2.0",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"[postfiat] HTTP {e.code} for {path}")
        return None
    except Exception as e:
        print(f"[postfiat] Error fetching {path}: {e}")
        return None


def _legacy_get(path: str, session_cookie: str) -> str:
    """Legacy cookie-based GET for app.postfiat.org profile scraping."""
    url = f"{PF_APP_BASE}{path}"
    headers = {
        "Cookie": session_cookie,
        "User-Agent": "Mozilla/5.0 (compatible; pf-scout/2.0)",
        "Accept": "text/html,application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"[postfiat-legacy] HTTP {e.code} for {path}")
        return ""


# ── Leaderboard (primary source) ───────────────────────────────────────────────


def _row_to_prospect(row: dict) -> Prospect:
    """Convert a leaderboard API row into a Prospect object."""
    wallet = row.get("wallet_address", "")
    summary = row.get("summary") or ""

    p = Prospect(handle=wallet, source="postfiat")
    p.display_name = summary

    # Capabilities → postfiat_capabilities
    caps = row.get("capabilities", [])
    if isinstance(caps, list):
        parsed = []
        for c in caps:
            if isinstance(c, str):
                parsed.append(c)
            elif isinstance(c, dict):
                parsed.append(c.get("description", c.get("text", "")))
        p.postfiat_capabilities = [c for c in parsed if c]

    # Expert knowledge → append to capabilities for scoring
    expert = row.get("expert_knowledge", [])
    if isinstance(expert, list):
        p.postfiat_capabilities += [k.get("domain", "") for k in expert if isinstance(k, dict) and k.get("domain")]

    # Task + reward signals
    p.postfiat_task_count = int(row.get("monthly_tasks", 0) or 0)
    p.postfiat_pft_earned = float(row.get("monthly_rewards", 0) or 0)

    # Enriched fields (stored in notes for scorer and output)
    alignment_score = row.get("alignment_score", 0) or 0
    alignment_tier = row.get("alignment_tier", "") or ""
    sybil_score = row.get("sybil_score", 0) or 0
    sybil_risk = row.get("sybil_risk", "") or ""
    weekly_rewards = row.get("weekly_rewards", 0) or 0
    weekly_tasks = row.get("weekly_tasks", 0) or 0
    lb_week = row.get("leaderboard_score_week", 0) or 0
    lb_month = row.get("leaderboard_score_month", 0) or 0
    is_published = row.get("is_published", False)
    user_id = row.get("user_id", "")

    p.notes = (
        f"alignment={alignment_score} ({alignment_tier}) | "
        f"sybil={sybil_score} ({sybil_risk}) | "
        f"monthly={p.postfiat_pft_earned:,.0f} PFT / {p.postfiat_task_count} tasks | "
        f"weekly={weekly_rewards:,.0f} PFT / {weekly_tasks} tasks | "
        f"lb_week={lb_week} lb_month={lb_month} | "
        f"published={'yes' if is_published else 'no'} | "
        f"user_id={user_id}"
    )

    # Stash raw API fields for scorer to use directly
    p._pf_alignment = alignment_score
    p._pf_sybil = sybil_score
    p._pf_sybil_risk = sybil_risk
    p._pf_alignment_tier = alignment_tier
    p._pf_weekly_rewards = weekly_rewards
    p._pf_lb_week = lb_week
    p._pf_lb_month = lb_month
    p._pf_is_published = is_published
    p._pf_user_id = user_id
    p._pf_summary = summary

    return p


def collect_leaderboard(
    jwt_token: str | None = None,
    min_alignment: int = 0,
    min_monthly_pft: float = 0,
    require_capabilities: bool = True,
) -> list[Prospect]:
    """
    Collect all Post Fiat leaderboard contributors as prospects.

    Args:
        jwt_token:            Bearer token for tasknode API. Falls back to PF_JWT_TOKEN env var.
        min_alignment:        Filter out contributors below this alignment score.
        min_monthly_pft:      Filter out contributors below this monthly PFT threshold.
        require_capabilities: Skip entries with no capabilities/expert_knowledge.

    Returns:
        List of Prospect objects, ready for scoring.
    """
    token = jwt_token or os.environ.get("PF_JWT_TOKEN", "")
    if not token:
        print("[postfiat] No JWT token. Set PF_JWT_TOKEN or pass jwt_token=.")
        return []

    data = _api_get("/api/leaderboard", token)
    if not data:
        return []

    rows = data.get("rows", [])
    prospects = []

    for row in rows:
        if require_capabilities and not row.get("capabilities") and not row.get("expert_knowledge"):
            continue
        alignment = row.get("alignment_score", 0) or 0
        monthly = row.get("monthly_rewards", 0) or 0
        if alignment < min_alignment:
            continue
        if monthly < min_monthly_pft:
            continue
        prospects.append(_row_to_prospect(row))

    return prospects


def get_leaderboard_totals(jwt_token: str | None = None) -> dict:
    """Return network-wide aggregate stats from the leaderboard."""
    token = jwt_token or os.environ.get("PF_JWT_TOKEN", "")
    if not token:
        return {}
    data = _api_get("/api/leaderboard", token)
    return data.get("totals", {}) if data else {}


# ── Single profile ──────────────────────────────────────────────────────────────


def collect_profile(
    wallet_address: str,
    jwt_token: str | None = None,
    session_cookie: str | None = None,
) -> Prospect | None:
    """
    Collect a single prospect's profile.

    Tries tasknode JWT API first (leaderboard lookup by wallet).
    Falls back to legacy cookie-based scraping if no JWT is available.

    Args:
        wallet_address:  XRP/PFT wallet address (r...).
        jwt_token:       tasknode Bearer token. Falls back to PF_JWT_TOKEN env var.
        session_cookie:  Legacy app.postfiat.org session cookie. Falls back to PF_SESSION_COOKIE.

    Returns:
        Prospect or None.
    """
    token = jwt_token or os.environ.get("PF_JWT_TOKEN", "")

    if token:
        # Pull full leaderboard and find this wallet (no per-wallet endpoint yet)
        data = _api_get("/api/leaderboard", token)
        if data:
            for row in data.get("rows", []):
                if row.get("wallet_address") == wallet_address:
                    return _row_to_prospect(row)
        # Not on leaderboard — still try to construct a minimal prospect
        p = Prospect(handle=wallet_address, source="postfiat")
        p.notes = "wallet not on leaderboard"
        return p

    # Legacy fallback: cookie-based profile scraping
    cookie = session_cookie or os.environ.get("PF_SESSION_COOKIE", "")
    if not cookie:
        print("[postfiat] No JWT token or session cookie. Set PF_JWT_TOKEN.")
        return None

    html = _legacy_get(f"/profile?address={wallet_address}", cookie)
    if not html:
        return None

    p = Prospect(handle=wallet_address, source="postfiat")
    caps_match = re.findall(r'"capability":\s*"([^"]+)"', html)
    if not caps_match:
        caps_match = re.findall(r'<span[^>]*class="[^"]*capability[^"]*"[^>]*>([^<]+)</span>', html)
    p.postfiat_capabilities = caps_match

    expert_match = re.findall(r'"expert_knowledge":\s*\[([^\]]+)\]', html)
    if expert_match:
        p.postfiat_capabilities += [t.strip().strip('"') for t in expert_match[0].split(",")]

    task_count_match = re.search(r'"task_count":\s*(\d+)', html)
    if task_count_match:
        p.postfiat_task_count = int(task_count_match.group(1))

    pft_match = re.search(r'"pft_earned":\s*([\d.]+)', html)
    if pft_match:
        p.postfiat_pft_earned = float(pft_match.group(1))

    return p


def collect_profiles(
    wallet_addresses: list[str],
    jwt_token: str | None = None,
    session_cookie: str | None = None,
) -> list[Prospect]:
    """Collect multiple profiles. Rate-limits to 1 req/sec."""
    prospects = []
    for addr in wallet_addresses:
        p = collect_profile(addr, jwt_token=jwt_token, session_cookie=session_cookie)
        if p:
            prospects.append(p)
        time.sleep(1.0)
    return prospects


# ── My network (contacts) ──────────────────────────────────────────────────────


def collect_my_contacts(jwt_token: str | None = None) -> list[Prospect]:
    """
    Return prospects from your own Post Fiat contact list.
    Cross-references leaderboard data to enrich each contact.

    Args:
        jwt_token: tasknode Bearer token. Falls back to PF_JWT_TOKEN.

    Returns:
        List of Prospect objects for each trusted contact.
    """
    token = jwt_token or os.environ.get("PF_JWT_TOKEN", "")
    if not token:
        print("[postfiat] No JWT token. Set PF_JWT_TOKEN.")
        return []

    contacts_data = _api_get("/api/contacts", token)
    leaderboard_data = _api_get("/api/leaderboard", token)

    if not contacts_data:
        return []

    # Build leaderboard index by wallet
    lb_index: dict[str, dict] = {}
    if leaderboard_data:
        for row in leaderboard_data.get("rows", []):
            lb_index[row.get("wallet_address", "")] = row

    prospects = []
    for contact in contacts_data.get("contacts", []):
        wallet = contact.get("wallet_address", "")
        if not wallet:
            continue

        if wallet in lb_index:
            p = _row_to_prospect(lb_index[wallet])
        else:
            p = Prospect(handle=wallet, source="postfiat")
            p.notes = f"contact (not on leaderboard) | last_msg={contact.get('last_message_at', '')}"

        p._pf_is_contact = True
        p._pf_trust_state = contact.get("trust_state", "")
        p._pf_last_message_at = contact.get("last_message_at", "")
        prospects.append(p)

    return prospects


# ── Network summary ─────────────────────────────────────────────────────────────


def get_network_summary(jwt_token: str | None = None) -> dict:
    """
    Return a human-readable network summary dict.

    Includes: active contributor count, total monthly/weekly output,
    top contributor by volume, top contributor by alignment.
    """
    token = jwt_token or os.environ.get("PF_JWT_TOKEN", "")
    if not token:
        return {}

    data = _api_get("/api/leaderboard", token)
    if not data:
        return {}

    rows = data.get("rows", [])
    totals = data.get("totals", {})
    active = [r for r in rows if (r.get("monthly_rewards") or 0) > 0]

    top_volume = max(active, key=lambda r: r.get("monthly_rewards", 0), default={})
    top_align = max(active, key=lambda r: r.get("alignment_score", 0), default={})

    return {
        "active_contributors": totals.get("active_contributors", len(active)),
        "monthly_pft": totals.get("rewards_month", 0),
        "monthly_tasks": totals.get("tasks_month", 0),
        "weekly_pft": totals.get("rewards_week", 0),
        "weekly_tasks": totals.get("tasks_week", 0),
        "top_by_volume": {
            "wallet": top_volume.get("wallet_address"),
            "summary": top_volume.get("summary"),
            "monthly_pft": top_volume.get("monthly_rewards"),
        },
        "top_by_alignment": {
            "wallet": top_align.get("wallet_address"),
            "summary": top_align.get("summary"),
            "alignment_score": top_align.get("alignment_score"),
        },
        "generated_at": data.get("generated_at"),
    }
