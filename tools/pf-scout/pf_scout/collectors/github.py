"""GitHub collector — scans a GitHub org or list of users for contributor profiles."""

import json
import os
import time
import urllib.error
import urllib.request

from .base import Prospect


def _gh_get(url: str, token: str | None = None) -> dict | list:
    token = token or os.environ.get("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "pf-scout/1.0"}
    if token:
        headers["Authorization"] = f"token {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        raise


def collect_org(org: str, token: str | None = None, max_repos: int = 30) -> list[Prospect]:
    """Collect contributors across all public repos in a GitHub org."""
    repos_url = f"https://api.github.com/orgs/{org}/repos?per_page={max_repos}&sort=updated"
    repos = _gh_get(repos_url, token)
    if not isinstance(repos, list):
        print(f"[github] Could not fetch repos for {org}")
        return []

    # Aggregate contributor commit counts across all repos
    contributors: dict[str, dict] = {}  # login → {commits, repos}
    for repo in repos:
        repo_name = repo.get("name", "")
        contribs_url = f"https://api.github.com/repos/{org}/{repo_name}/contributors?per_page=50"
        contribs = _gh_get(contribs_url, token)
        if not isinstance(contribs, list):
            continue
        for c in contribs:
            login = c.get("login", "")
            if "[bot]" in login:
                continue
            if login not in contributors:
                contributors[login] = {"total_commits": 0, "repos": {}}
            contributors[login]["total_commits"] += c.get("contributions", 0)
            contributors[login]["repos"][repo_name] = c.get("contributions", 0)
        time.sleep(0.3)  # rate limit courtesy

    # Enrich each contributor with their profile
    prospects = []
    for login, data in contributors.items():
        profile = _gh_get(f"https://api.github.com/users/{login}", token)
        if not profile:
            continue
        p = Prospect(
            handle=login,
            display_name=profile.get("name") or login,
            source="github",
            github_repos=profile.get("public_repos", 0),
            github_followers=profile.get("followers", 0),
            github_contributions=data["repos"],
            github_bio=profile.get("bio") or "",
            github_company=profile.get("company") or "",
            github_location=profile.get("location") or "",
        )
        prospects.append(p)
        time.sleep(0.2)

    return prospects


def collect_users(handles: list[str], token: str | None = None) -> list[Prospect]:
    """Collect profiles for a specific list of GitHub handles."""
    prospects = []
    for handle in handles:
        profile = _gh_get(f"https://api.github.com/users/{handle}", token)
        if not profile or "login" not in profile:
            print(f"[github] Not found: {handle}")
            continue
        p = Prospect(
            handle=handle,
            display_name=profile.get("name") or handle,
            source="github",
            github_repos=profile.get("public_repos", 0),
            github_followers=profile.get("followers", 0),
            github_bio=profile.get("bio") or "",
            github_company=profile.get("company") or "",
            github_location=profile.get("location") or "",
        )
        prospects.append(p)
        time.sleep(0.2)
    return prospects
