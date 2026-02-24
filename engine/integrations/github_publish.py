"""engine.integrations.github_publish

Publish off-chain EAS attestations to a GitHub repo as Issues.
Fail-open: never raises, returns None on any failure.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

_MAX_ATTEMPTS = 3
_BACKOFF_BASE = 1.0
_BACKOFF_CAP = 8.0

# Status codes that are not worth retrying (auth / not-found errors)
_NO_RETRY_STATUSES = {401, 403, 404}


def _redact_token(token: str) -> str:
    """Return a redacted token string safe for logging."""
    if len(token) <= 8:
        return "***"
    return token[:4] + "****" + token[-2:]


def _build_issue_body(
    *,
    attestation: dict[str, Any],
    contributor_id: str,
    node_id: str,
    name: str,
    role: str,
    registered_at: str,
) -> str:
    uid = str(attestation.get("uid") or "")
    schema_uid = str(attestation.get("schema_uid") or "")
    attester = str(attestation.get("attester") or "")
    recipient = str(attestation.get("recipient") or "")
    ts = attestation.get("time", "")

    lines = [
        f"* uid: {uid}",
        f"* schema_uid: {schema_uid}",
        f"* attester: {attester}",
        f"* recipient: {recipient}",
        f"* time: {ts}",
        f"* contributor_id: {contributor_id}",
        f"* node_id: {node_id}",
        f"* name: {name}",
        f"* role: {role}",
        f"* registered_at: {registered_at}",
        "",
        "```json",
        json.dumps(attestation, indent=2, sort_keys=True, default=str),
        "```",
    ]
    return "\n".join(lines)


def publish_attestation_to_github(
    *,
    attestation: dict[str, Any],
    contributor_id: str,
    node_id: str,
    name: str,
    role: str,
    registered_at: str,
    owner: str,
    repo: str,
    token: str,
    labels: list[str] | None = None,
) -> dict[str, Any] | None:
    """Create a GitHub Issue for the given attestation.

    Returns ``{issue_url, issue_number, owner, repo}`` on success, or
    ``None`` on any failure (fail-open: never raises).
    """
    if not token:
        logger.warning("github_publish: no token provided — skipping")
        return None

    uid = str(attestation.get("uid") or "unknown")
    title = f"attestation: {uid}"
    body = _build_issue_body(
        attestation=attestation,
        contributor_id=contributor_id,
        node_id=node_id,
        name=name,
        role=role,
        registered_at=registered_at,
    )

    payload: dict[str, Any] = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels

    url = f"{GITHUB_API}/repos/{owner}/{repo}/issues"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    attempt = 0
    last_status: int | None = None

    try:
        with httpx.Client(timeout=15.0) as client:
            while attempt < _MAX_ATTEMPTS:
                attempt += 1
                try:
                    resp = client.post(url, json=payload, headers=headers)
                    last_status = resp.status_code
                except Exception as exc:
                    logger.warning("github_publish: request error on attempt %d: %s", attempt, exc)
                    if attempt >= _MAX_ATTEMPTS:
                        return None
                    sleep_s = min(_BACKOFF_BASE * (2 ** (attempt - 1)), _BACKOFF_CAP)
                    time.sleep(sleep_s)
                    continue

                if resp.status_code == 201:
                    data = resp.json()
                    return {
                        "issue_url": str(data.get("html_url") or ""),
                        "issue_number": int(data.get("number") or 0),
                        "owner": owner,
                        "repo": repo,
                    }

                if resp.status_code in _NO_RETRY_STATUSES:
                    # Redact token in logs
                    logger.warning(
                        "github_publish: auth/not-found error %d for %s/%s (token=%s) — aborting",
                        resp.status_code,
                        owner,
                        repo,
                        _redact_token(token),
                    )
                    return None

                if resp.status_code == 429 or resp.status_code >= 500:
                    logger.warning(
                        "github_publish: retryable status %d on attempt %d/%d",
                        resp.status_code,
                        attempt,
                        _MAX_ATTEMPTS,
                    )
                    if attempt >= _MAX_ATTEMPTS:
                        return None
                    sleep_s = min(_BACKOFF_BASE * (2 ** (attempt - 1)), _BACKOFF_CAP)
                    time.sleep(sleep_s)
                    continue

                # Unexpected status — fail immediately
                logger.warning(
                    "github_publish: unexpected status %d — aborting",
                    resp.status_code,
                )
                return None

    except Exception as exc:
        logger.warning("github_publish: unexpected error: %s", exc)
        return None

    logger.warning("github_publish: all %d attempts exhausted (last status=%s)", _MAX_ATTEMPTS, last_status)
    return None
