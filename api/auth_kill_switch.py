from __future__ import annotations

import hmac

from fastapi import Depends, Header

from api.deps import get_config
from api.errors import B1e55edError
from engine.core.config import Config


def require_kill_switch_token(
    authorization: str | None = Header(default=None, alias="Authorization"),
    config: Config = Depends(get_config),
) -> None:
    """Require Authorization: Bearer <kill_switch_token>.

    Uses a separate token from the general API auth_token.

    If kill_switch_token is not configured, we treat this as a hard failure:
    kill switch endpoints must not run without explicit auth.
    """

    expected = str(getattr(config.api, "kill_switch_token", "") or "")
    if not expected:
        raise B1e55edError(
            code="auth.kill_switch_token_missing",
            message="Kill switch auth token is not configured",
            status=500,
        )

    if not authorization:
        raise B1e55edError(
            code="auth.missing_token",
            message="Missing bearer token",
            status=401,
        )

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise B1e55edError(
            code="auth.invalid_header",
            message="Invalid authorization header",
            status=401,
        )

    token = parts[1].strip()
    if not hmac.compare_digest(token, expected):
        raise B1e55edError(
            code="auth.invalid_token",
            message="Invalid bearer token",
            status=401,
        )


KillSwitchAuthDep = Depends(require_kill_switch_token)
