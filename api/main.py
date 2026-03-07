from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from api.errors import B1e55edError, b1e55ed_error_handler
from api.routes import get_api_router
from engine.core.config import Config
from engine.core.rate_limiter import ApiRateLimiter


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a request_id to every request and echo it in the response headers."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class ApiRateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Allow health/docs without rate limiting
        if request.url.path in ("/api/v1/health", "/docs", "/openapi.json"):
            return await call_next(request)

        # Key by bearer token if present, else by client IP.
        auth = request.headers.get("authorization") or ""
        key = "ip:" + (request.client.host if request.client else "unknown")
        if auth.lower().startswith("bearer "):
            # Avoid storing raw token; use a stable hash.
            import hashlib

            tok = auth.split(" ", 1)[1].strip().encode("utf-8")
            key = "token:" + hashlib.sha256(tok).hexdigest()

        db = getattr(request.app.state, "db", None)
        if db is None:
            return await call_next(request)

        limiter = ApiRateLimiter(db, window_seconds=60, max_requests=240)
        allowed, retry_after = limiter.allow(key=key)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "rate_limited",
                        "message": "Rate limit exceeded",
                        "retry_after": retry_after,
                    }
                },
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)


class IdentityGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Dev/test bypass
        if os.environ.get("B1E55ED_DEV_MODE", "").lower() in ("1", "true", "yes"):
            import logging

            logging.getLogger("b1e55ed.security").critical("B1E55ED_DEV_MODE is active — IdentityGateMiddleware is BYPASSED. Never use in production.")
            return await call_next(request)

        # Allow health/docs without identity (monitoring + introspection)
        if request.url.path in ("/api/v1/health", "/docs", "/openapi.json"):
            return await call_next(request)

        from engine.core.identity_gate import load_identity

        identity = load_identity()
        if identity is None:
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "IDENTITY_REQUIRED",
                        "message": "Forged identity required. Run `b1e55ed identity forge` to create one.",
                    }
                },
            )

        return await call_next(request)


def create_app() -> FastAPI:
    start = time.monotonic()

    # Security check: refuse to start with empty auth_token unless explicitly overridden
    from pathlib import Path

    from engine.core.paths import config_dir

    # In production installs, user config lives in ~/.b1e55ed/config/user.yaml.
    # In dev checkouts, it lives relative to the repo root (Path.cwd()).
    # Always prefer the canonical production path; fall back to cwd for dev.
    root = Path.cwd()
    user_path = config_dir() / "user.yaml"
    if not user_path.exists():
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

        # Expose config/db in app state for dependency injection + tests.
        app.state.config = getattr(app.state, "config", None) or config

        import logging as _log

        if getattr(config.eas, "enabled", True):
            if not getattr(config.eas, "rpc_url", ""):
                _log.getLogger("b1e55ed.startup").info("EAS off-chain attestations enabled. Set eas.rpc_url to also enable on-chain proofs.")
        else:
            _log.getLogger("b1e55ed.startup").warning("EAS attestation is DISABLED (eas.enabled=false in config).")

        from engine.core.database import Database

        created_db = False
        if getattr(app.state, "db", None) is None:
            from engine.core.paths import data_dir

            # The map is not the territory. Path.cwd() is not the database.
            app.state.db = Database(data_dir() / "brain.db")
            created_db = True

        # Auto-register local node as an operator contributor.
        try:
            from engine.core.contributors import ContributorRegistry
            from engine.integrations.github_publish import make_publisher
            from engine.security import ensure_identity

            ident = ensure_identity().identity
            _cfg = app.state.config
            _pub_cfg = _cfg.publish.github
            _pub = (
                make_publisher(
                    owner=_pub_cfg.owner,
                    repo=_pub_cfg.repo,
                    token=_pub_cfg.token,
                    labels=_pub_cfg.labels,
                )
                if _pub_cfg.token
                else None
            )
            reg = ContributorRegistry(app.state.db, github_publisher=_pub)
            if reg.get_by_node(ident.node_id) is None:
                reg.register(
                    node_id=ident.node_id,
                    name="local-operator",
                    role="operator",
                    metadata={"public_key": ident.public_key_hex},
                )
        except Exception:
            # Never block startup on contributor registration.
            pass

        # Best-effort crash-recovery sweep: find closed positions without karma intents.
        try:
            from engine.execution.recovery import recover_missing_karma_intents
            from engine.security import ensure_identity as _ensure_identity

            _ident = _ensure_identity().identity
            _recovered = recover_missing_karma_intents(
                db=app.state.db,
                config=app.state.config,
                identity=_ident,
            )
            if _recovered > 0:
                import logging as _log

                _log.getLogger("b1e55ed.startup").info("Recovered %d missing karma intents on startup", _recovered)
        except Exception:
            pass  # Never block startup on recovery failure.

        yield

        # Best-effort close DB if we created it in this lifespan.
        db = getattr(app.state, "db", None)
        try:
            if created_db and db is not None:
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
        {"name": "contributors", "description": "Contributor registry, scoring, and leaderboard."},
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

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = str(getattr(request.state, "request_id", uuid.uuid4()))
        logging.getLogger("b1e55ed.api").error(
            "Unhandled exception on %s %s [request_id=%s]",
            request.method,
            request.url.path,
            request_id,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "An internal error occurred",
                    "request_id": request_id,
                }
            },
        )

    # Request ID middleware — must be added FIRST so request_id is always
    # available for downstream middleware and exception handlers.
    app.add_middleware(RequestIdMiddleware)

    # API rate limiting (SEC1)
    app.add_middleware(ApiRateLimitMiddleware)

    # Identity gate: require forged identity for all endpoints (except health/docs)
    app.add_middleware(IdentityGateMiddleware)

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

    # MCP (Model Context Protocol) server — mounted at /mcp (no /api/v1 prefix)
    from api.routes.mcp import router as mcp_router

    app.include_router(mcp_router)

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        """API info page — lists key endpoints."""
        import engine as _engine

        return {
            "name": "b1e55ed",
            "version": _engine.__version__,
            "docs": "/docs",
            "health": "/api/v1/health",
            "endpoints": {
                "contributors": "/api/v1/contributors",
                "signals": "/api/v1/signals",
                "producers": "/api/v1/producers",
                "karma": "/api/v1/karma",
                "positions": "/api/v1/positions",
                "brain": "/api/v1/brain",
                "oracle": "/api/v1/oracle/producers/{id}/provenance",
                "config": "/api/v1/config",
                "metrics": "/api/v1/metrics",
                "mcp": "/mcp",
            },
        }

    return app


# Module-level app for uvicorn (e.g. `uvicorn api.main:app`).
# Guarded so test imports don't crash when auth_token isn't configured.
try:
    app = create_app()
except RuntimeError:
    app = None
