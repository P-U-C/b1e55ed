from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.errors import B1e55edError, b1e55ed_error_handler
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

    openapi_tags = [
        {"name": "health", "description": "Liveness and version metadata."},
        {"name": "brain", "description": "Cycle orchestration and system-level state."},
        {"name": "signals", "description": "Read-only access to emitted signals."},
        {"name": "positions", "description": "Read-only access to positions projected from events."},
        {"name": "regime", "description": "Market regime projections and state."},
        {"name": "producers", "description": "Producer registration and health."},
        {"name": "config", "description": "Runtime configuration inspection."},
        {"name": "karma", "description": "Karma accounting and settlement state."},
    ]

    app = FastAPI(
        title="b1e55ed API",
        description="b1e55ed signal engine — programmatic alpha hunting",
        version="2.0.0",
        openapi_tags=openapi_tags,
        lifespan=lifespan,
    )

    app.add_exception_handler(B1e55edError, b1e55ed_error_handler)

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

    app.include_router(get_api_router(), prefix="/api/v1")
    return app


# Module-level app for uvicorn (e.g. `uvicorn api.main:app`).
# Guarded so test imports don't crash when auth_token isn't configured.
try:
    app = create_app()
except RuntimeError:
    app = None
