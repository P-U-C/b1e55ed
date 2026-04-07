from __future__ import annotations

from fastapi import APIRouter

from api.routes import (
    agents,
    alerts,
    artifacts,
    benchmarks,
    brain,
    capabilities,
    chain,
    cockpit,
    config,
    contributors,
    events,
    health,
    karma,
    kill_switch,
    mcp,
    metrics,
    oracle,
    outcomes,
    positions,
    producers,
    producers_feedback,
    regime,
    signals,
    signals_validate,
    social,
    spi,
    spi_admin,
    trace,
    universe,
)


def get_api_router() -> APIRouter:
    router = APIRouter()

    router.include_router(cockpit.router, tags=["cockpit"])
    router.include_router(benchmarks.router, tags=["benchmarks"])
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
    router.include_router(capabilities.router, tags=["capabilities"])
    router.include_router(contributors.router, tags=["contributors"])
    router.include_router(config.router, tags=["config"])
    router.include_router(universe.router, tags=["universe"])
    router.include_router(karma.router, tags=["karma"])
    router.include_router(social.router, tags=["social"])
    router.include_router(trace.router, tags=["trace"])
    router.include_router(spi.router, tags=["spi"])
    router.include_router(spi_admin.router, tags=["spi-admin"])

    # ERC-8004 chain registration status
    router.include_router(chain.router, tags=["chain"])

    # ERC-8004 agent manifests
    router.include_router(agents.router, tags=["agents"])

    # ERC-8004 E2: outcome provenance endpoint (fileURI target)
    router.include_router(outcomes.router, tags=["outcomes"])

    # Oracle: public-facing provenance endpoint (no auth dependency)
    router.include_router(oracle.router, prefix="/oracle", tags=["oracle"])
    router.include_router(mcp.router, tags=["mcp"])
    router.include_router(artifacts.router, tags=["artifacts"])
    router.include_router(agents.router, tags=["agents"])

    # Dashboard compatibility stubs (/alerts, /conviction)
    router.include_router(alerts.router, tags=["dashboard-compat"])

    return router
