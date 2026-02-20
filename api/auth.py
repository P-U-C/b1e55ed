from __future__ import annotations

from fastapi import Depends, Header

from api.deps import get_config
from api.errors import B1e55edError
from engine.core.config import Config


def require_bearer_token(
    authorization: str | None = Header(default=None, alias="Authorization"),
    config: Config = Depends(get_config),
) -> None:
    """Require Authorization: Bearer <token>.

    If config.api.auth_token is empty, auth is treated as disabled.
    """

    expected = str(getattr(config.api, "auth_token", "") or "")
    if not expected:
        return

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
    if token != expected:
        raise B1e55edError(
            code="auth.invalid_token",
            message="Invalid bearer token",
            status=401,
        )


AuthDep = Depends(require_bearer_token)
