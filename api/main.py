from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import get_api_router


def create_app() -> FastAPI:
    start = time.monotonic()

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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"] ,
        allow_headers=["*"] ,
    )

    app.include_router(get_api_router())
    return app


app = create_app()
