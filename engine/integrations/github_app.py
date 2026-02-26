"""engine.integrations.github_app

GitHub App authentication helper.
Generates short-lived installation tokens (1hr) from a GitHub App private key.

Required env vars (or pass directly):
  B1E55ED_GITHUB_APP_ID          — numeric App ID
  B1E55ED_GITHUB_INSTALLATION_ID — numeric Installation ID
  B1E55ED_GITHUB_APP_KEY         — PEM private key (raw string or path to .pem file)
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

# Token lifetime constants
_TOKEN_LIFETIME_SECONDS = 3600  # GitHub installation tokens last 1hr
_TOKEN_REFRESH_BUFFER = 300  # Refresh when <5 min remain


def _b64url(data: bytes) -> str:
    """Base64url-encode bytes (no padding)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _load_private_key(pem: str) -> RSAPrivateKey:
    """Load an RSA private key from a PEM string."""
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, RSAPrivateKey):
        raise ValueError("GitHub App private key must be an RSA key")
    return key


def _resolve_pem(raw: str) -> str:
    """
    If ``raw`` looks like a file path that exists, read it.
    Otherwise treat it as the PEM content directly.
    """
    # Strip surrounding whitespace
    raw = raw.strip()
    if raw and "\n" not in raw and os.path.isfile(raw):
        return open(raw, encoding="utf-8").read()
    return raw


def generate_jwt(app_id: int, private_key_pem: str) -> str:
    """Generate a signed RS256 JWT for GitHub App authentication.

    Standard GitHub App JWT flow:
      - iat = now - 60  (account for clock skew)
      - exp = now + 540 (9 min; max is 10 min)
      - iss = app_id (as string per GitHub docs)

    Args:
        app_id: Numeric GitHub App ID.
        private_key_pem: PEM-encoded RSA private key string (or path to .pem file).

    Returns:
        Signed JWT string in ``header.payload.signature`` format.
    """
    pem = _resolve_pem(private_key_pem)
    private_key = _load_private_key(pem)

    now = int(time.time())
    header: dict[str, Any] = {"alg": "RS256", "typ": "JWT"}
    claims: dict[str, Any] = {
        "iss": str(app_id),
        "iat": now - 60,
        "exp": now + 540,
    }

    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode()

    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    sig_b64 = _b64url(signature)

    return f"{header_b64}.{payload_b64}.{sig_b64}"


def get_installation_token(
    app_id: int,
    installation_id: int,
    private_key_pem: str,
) -> str:
    """Exchange a GitHub App JWT for a short-lived installation access token.

    Calls ``POST /app/installations/{installation_id}/access_tokens`` and
    returns the token string (valid ~1hr).

    Args:
        app_id: Numeric GitHub App ID.
        installation_id: Numeric Installation ID.
        private_key_pem: PEM-encoded RSA private key string (or path to .pem file).

    Returns:
        Installation access token string.

    Raises:
        RuntimeError: If the API call fails.
    """
    jwt = generate_jwt(app_id, private_key_pem)
    url = f"{GITHUB_API}/app/installations/{installation_id}/access_tokens"
    headers = {
        "Authorization": f"Bearer {jwt}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, headers=headers)
    except Exception as exc:
        raise RuntimeError(f"github_app: HTTP error fetching installation token: {exc}") from exc

    if resp.status_code != 201:
        raise RuntimeError(f"github_app: failed to get installation token (status={resp.status_code}, body={resp.text[:200]})")

    data = resp.json()
    token = data.get("token")
    if not token:
        raise RuntimeError(f"github_app: no token in response: {data!r}")

    logger.debug("github_app: installation token obtained (expires_at=%s)", data.get("expires_at"))
    return str(token)


class GitHubAppAuth:
    """Thread-safe GitHub App authenticator with token caching.

    Caches the installation access token and refreshes it automatically
    when less than 5 minutes remain before expiry.

    Usage::

        auth = GitHubAppAuth.from_env()
        token = auth.get_token()   # refreshes if needed
    """

    def __init__(
        self,
        app_id: int,
        installation_id: int,
        private_key_pem: str,
    ) -> None:
        self._app_id = app_id
        self._installation_id = installation_id
        self._private_key_pem = _resolve_pem(private_key_pem)
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at: float = 0.0  # Unix timestamp

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_token(self) -> str:
        """Return a valid installation access token, refreshing if necessary."""
        with self._lock:
            if self._token and time.time() < (self._expires_at - _TOKEN_REFRESH_BUFFER):
                return self._token
            return self._refresh()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _refresh(self) -> str:
        """Fetch a new installation token and cache it. Must be called under self._lock."""
        logger.debug("github_app: refreshing installation token for app_id=%s", self._app_id)
        token = get_installation_token(
            self._app_id,
            self._installation_id,
            self._private_key_pem,
        )
        self._token = token
        # GitHub tokens last 1hr; track expiry conservatively
        self._expires_at = time.time() + _TOKEN_LIFETIME_SECONDS
        return token

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> GitHubAppAuth:
        """Construct a GitHubAppAuth from environment variables.

        Required env vars:
          B1E55ED_GITHUB_APP_ID          — numeric App ID
          B1E55ED_GITHUB_INSTALLATION_ID — numeric Installation ID
          B1E55ED_GITHUB_APP_KEY         — PEM private key (raw or path to .pem file)

        Raises:
            RuntimeError: If any required env var is missing or invalid.
        """
        missing: list[str] = []

        app_id_raw = os.environ.get("B1E55ED_GITHUB_APP_ID", "")
        if not app_id_raw:
            missing.append("B1E55ED_GITHUB_APP_ID")

        installation_id_raw = os.environ.get("B1E55ED_GITHUB_INSTALLATION_ID", "")
        if not installation_id_raw:
            missing.append("B1E55ED_GITHUB_INSTALLATION_ID")

        private_key_pem = os.environ.get("B1E55ED_GITHUB_APP_KEY", "")
        if not private_key_pem:
            missing.append("B1E55ED_GITHUB_APP_KEY")

        if missing:
            raise RuntimeError(
                f"github_app: missing required environment variable(s): {', '.join(missing)}. "
                "Set B1E55ED_GITHUB_APP_ID, B1E55ED_GITHUB_INSTALLATION_ID, "
                "and B1E55ED_GITHUB_APP_KEY to use GitHub App auth."
            )

        try:
            app_id = int(app_id_raw)
        except ValueError:
            raise RuntimeError(f"github_app: B1E55ED_GITHUB_APP_ID must be a number, got: {app_id_raw!r}") from None

        try:
            installation_id = int(installation_id_raw)
        except ValueError:
            raise RuntimeError(f"github_app: B1E55ED_GITHUB_INSTALLATION_ID must be a number, got: {installation_id_raw!r}") from None

        return cls(app_id=app_id, installation_id=installation_id, private_key_pem=private_key_pem)

    def __repr__(self) -> str:
        return f"GitHubAppAuth(app_id={self._app_id}, installation_id={self._installation_id}, cached={'yes' if self._token else 'no'})"
