from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from api.deps import get_config
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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization header")

    token = parts[1].strip()
    if token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")


AuthDep = Depends(require_bearer_token)
