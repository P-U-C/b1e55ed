from __future__ import annotations

from fastapi import APIRouter

from api.routes import brain, config, contributors, health, karma, kill_switch, positions, producers, regime, signals


def get_api_router() -> APIRouter:
    router = APIRouter()

    router.include_router(health.router, tags=["health"])
    router.include_router(brain.router, tags=["brain"])
    router.include_router(kill_switch.router)
    router.include_router(signals.router, tags=["signals"])
    router.include_router(positions.router, tags=["positions"])
    router.include_router(regime.router, tags=["regime"])
    router.include_router(producers.router, tags=["producers"])
    router.include_router(contributors.router, tags=["contributors"])
    router.include_router(config.router, tags=["config"])
    router.include_router(karma.router, tags=["karma"])

    return router
