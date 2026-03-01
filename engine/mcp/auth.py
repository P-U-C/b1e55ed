"""engine.mcp.auth

Optional API key authentication for MCP endpoints.

When `config.mcp.require_auth = True`, all /api/v1/mcp/* endpoints require
an `X-MCP-Key` header matching one of the configured API keys.

When `require_auth = False` (default), endpoints are open — suitable for
local/operator deployments where the port is not publicly exposed.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable

from fastapi import Header, HTTPException, status


def validate_mcp_key(key: str, allowed_keys: list[str]) -> bool:
    """Constant-time comparison against allowed keys. Returns True if valid."""

    return any(hmac.compare_digest(key, k) for k in allowed_keys)


def get_mcp_auth_dependency(config) -> Callable[[str | None], None]:
    """Return a FastAPI dependency for optional MCP API-key authentication."""

    if not getattr(config.mcp, "require_auth", False):

        def _allow_all(_x_mcp_key: str | None = Header(default=None, alias="X-MCP-Key")) -> None:
            return None

        return _allow_all

    allowed_keys = list(getattr(config.mcp, "api_keys", []) or [])

    def _require_valid_key(x_mcp_key: str | None = Header(default=None, alias="X-MCP-Key")) -> None:
        if not x_mcp_key or not validate_mcp_key(x_mcp_key, allowed_keys):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid MCP API key")

    return _require_valid_key
