from __future__ import annotations

from fastapi import APIRouter

from api.routes import (
    brain,
    cockpit,
    config,
    contributors,
    events,
    health,
    karma,
    kill_switch,
    metrics,
    oracle,
    positions,
    producers,
    producers_feedback,
    regime,
    signals,
    signals_validate,
    trace,
)


def get_api_router() -> APIRouter:
    router = APIRouter()

    router.include_router(cockpit.router, tags=["cockpit"])
    router.include_router(health.router, tags=["health"])
    router.include_router(metrics.router, tags=["metrics"])
    router.include_router(brain.router, tags=["brain"])
    router.include_router(kill_switch.router)
    router.include_router(events.router, tags=["events"])
    router.include_router(signals.router, tags=["signals"])
    router.include_router(signals_validate.router, tags=["signals"])
    router.include_router(positions.router, tags=["positions"])
    router.include_router(regime.router, tags=["regime"])
    router.include_router(producers.router, tags=["producers"])
    router.include_router(producers_feedback.router, tags=["producers"])
    router.include_router(contributors.router, tags=["contributors"])
    router.include_router(config.router, tags=["config"])
    router.include_router(karma.router, tags=["karma"])
    router.include_router(trace.router, tags=["trace"])

    # Oracle: public-facing provenance endpoint (no auth dependency)
    router.include_router(oracle.router, prefix="/oracle", tags=["oracle"])

    return router
