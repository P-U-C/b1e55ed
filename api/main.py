from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import get_api_router
from engine.core.config import Config


def create_app() -> FastAPI:
    start = time.monotonic()

    # Security check: refuse to start with empty auth_token unless explicitly overridden
    from pathlib import Path

    root = Path.cwd()
    user_path = root / "config" / "user.yaml"
    if user_path.exists():
        config = Config.from_yaml(user_path)
    else:
        config = Config.from_repo_defaults(root)
    auth_token = str(getattr(config.api, "auth_token", "") or "")
    insecure_ok = os.environ.get("B1E55ED_INSECURE_OK", "").lower() in ("1", "true", "yes")

    if not auth_token and not insecure_ok:
        msg = (
            "❌ SECURITY ERROR: API auth_token is empty\n"
            "\n"
            "Set B1E55ED_API__AUTH_TOKEN environment variable or add to config:\n"
            "  api:\n"
            "    auth_token: your-secret-token\n"
            "\n"
            "To run without auth (dev/test only), set B1E55ED_INSECURE_OK=1"
        )
        raise RuntimeError(msg)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.started_at = start
        yield
        # Best-effort close DB if it was placed in state
        db = getattr(app.state, "db", None)
        try:
            if db is not None:
                db.close()
        except Exception:
            pass

    app = FastAPI(title="b1e55ed API", version="2.0.0", lifespan=lifespan)

    # CORS: only enable if origins explicitly configured
    cors_origins = getattr(config.api, "cors_origins", [])
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(get_api_router())
    return app


# Module-level app for uvicorn (e.g. `uvicorn api.main:app`).
# Guarded so test imports don't crash when auth_token isn't configured.
try:
    app = create_app()
except RuntimeError:
    app = None  # type: ignore[assignment]
