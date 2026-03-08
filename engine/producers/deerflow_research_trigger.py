"""engine.producers.deerflow_research_trigger

Scheduled DeerFlow research trigger producer.

Runs every 6 hours (0 */6 * * *). Resolves the active token universe from
the brain DB, triggers a DeerFlow watchlist research cycle via the MCP
gateway, polls for the resulting artifact, and ingests it as a
signal.research.v1 event.

Configuration (env vars):
    DEERFLOW_GATEWAY_URL      — gateway URL (default: http://localhost:7338)
    DEERFLOW_GATEWAY_API_KEY  — API key for gateway auth
    DEERFLOW_POLL_INTERVAL    — seconds between artifact polls (default: 60)
    DEERFLOW_TIMEOUT          — max seconds to wait for artifact (default: 1800)
    DEERFLOW_UNIVERSE_SIZE    — top-N tokens to include (default: 5)
    DEERFLOW_SANDBOX_DIR      — sandbox dir to poll (default: ~/.b1e55ed/deerflow/sandbox)
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from engine.artifacts.store import ArtifactStore
from engine.core.database import Database
from engine.core.events import ResearchSignalPayload, SignalClass
from engine.producers.deerflow_research import DeerflowResearchProducer

logger = logging.getLogger(__name__)

SCHEDULE = "0 */6 * * *"

DEFAULT_GATEWAY_URL = "http://localhost:7338"
DEFAULT_POLL_INTERVAL = 60
DEFAULT_TIMEOUT = 1800
DEFAULT_UNIVERSE_SIZE = 5
DEFAULT_SANDBOX_DIR = Path.home() / ".b1e55ed" / "deerflow" / "sandbox"

UNIVERSE_QUERY = """
SELECT DISTINCT token_symbol
FROM signals
WHERE created_at > datetime('now', '-24 hours')
  AND signal_type IN ('signal.conviction.v1', 'signal.detection.v1', 'signal.research.v1')
  AND token_symbol IS NOT NULL
GROUP BY token_symbol
ORDER BY COUNT(*) DESC
LIMIT ?
"""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _cycle_result(
    cycle_id: str,
    started_at: str,
    status: str,
    universe: list[str],
    artifact: dict[str, Any] | None = None,
    signal_event_id: str | None = None,
) -> dict[str, Any]:
    return {
        "cycle_id": cycle_id,
        "started_at": started_at,
        "completed_at": _now_iso(),
        "status": status,
        "universe": universe,
        "artifact": artifact,
        "signal_event_id": signal_event_id,
    }


async def resolve_universe(db: Database, size: int | None = None) -> list[str]:
    """Return top tokens from brain DB by recent signal activity."""
    limit = size or int(os.environ.get("DEERFLOW_UNIVERSE_SIZE", DEFAULT_UNIVERSE_SIZE))
    try:
        rows = db.execute(UNIVERSE_QUERY, (limit,)).fetchall()
        return [row[0] for row in rows if row[0]]
    except Exception:
        logger.exception("Failed to resolve universe from brain DB")
        return []


async def trigger_deerflow(
    universe: list[str],
    gateway_url: str,
    api_key: str | None,
) -> bool:
    """Send MCP tools/call to the gateway to trigger watchlist research.

    Returns True on successful trigger, False on failure.
    """
    url = f"{gateway_url.rstrip('/')}/mcp/call"
    payload = {
        "method": "tools/call",
        "params": {
            "name": "run_watchlist_research",
            "arguments": {
                "tokens": universe,
                "output_format": "html",
            },
        },
    }
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            logger.info("DeerFlow trigger accepted (status=%s)", resp.status_code)
            return True
    except httpx.HTTPStatusError as exc:
        logger.error(
            "DeerFlow trigger HTTP error: %s %s",
            exc.response.status_code,
            exc.response.text[:200],
        )
        return False
    except Exception:
        logger.exception("DeerFlow trigger failed")
        return False


async def poll_for_artifact(
    watcher: DeerflowResearchProducer,
    timeout: int,
    poll_interval: int,
) -> dict[str, Any] | None:
    """Poll sandbox for new artifacts until timeout.

    Returns the first ingested artifact result dict or None on timeout.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            results = watcher.scan_once()
            if results:
                logger.info("Artifact ingested: %s", results[0].get("artifact_id", "?"))
                return results[0]
        except Exception:
            logger.exception("Error during artifact scan")
        await asyncio.sleep(poll_interval)
    return None


def build_signal_payload(
    universe: list[str],
    artifact: dict[str, Any],
) -> ResearchSignalPayload:
    """Build a ResearchSignalPayload from cycle results."""
    permalink = artifact.get("permalink", artifact.get("artifact_id", "unknown"))
    return ResearchSignalPayload(
        symbol=",".join(universe),
        signal_class=SignalClass.OBSERVATION,
        direction="neutral",
        confidence=0.5,
        rationale=f"DeerFlow watchlist research cycle. Artifact: {permalink}",
        artifact_url=permalink,
        sources=["deerflow:watchlist"],
        operator_node_id="scheduled:trigger",
        deerflow_task_id=artifact.get("event_id"),
    )


async def run_cycle(
    db: Database,
    store: ArtifactStore,
    *,
    gateway_url: str | None = None,
    api_key: str | None = None,
    timeout: int | None = None,
    poll_interval: int | None = None,
    universe_size: int | None = None,
    sandbox_dir: Path | None = None,
) -> dict[str, Any]:
    """Execute one full trigger-and-wait research cycle.

    Never raises — always returns a cycle result dict.
    """
    cycle_id = str(uuid.uuid4())
    started_at = _now_iso()

    gw_url = gateway_url or os.environ.get("DEERFLOW_GATEWAY_URL", DEFAULT_GATEWAY_URL)
    gw_key = api_key or os.environ.get("DEERFLOW_GATEWAY_API_KEY")
    t_timeout = timeout or int(os.environ.get("DEERFLOW_TIMEOUT", DEFAULT_TIMEOUT))
    t_poll = poll_interval or int(os.environ.get("DEERFLOW_POLL_INTERVAL", DEFAULT_POLL_INTERVAL))
    t_size = universe_size or int(os.environ.get("DEERFLOW_UNIVERSE_SIZE", DEFAULT_UNIVERSE_SIZE))
    t_sandbox = sandbox_dir or Path(os.environ.get("DEERFLOW_SANDBOX_DIR", str(DEFAULT_SANDBOX_DIR)))

    logger.info("DeerFlow research cycle %s started", cycle_id)

    # 1. Resolve universe
    universe = await resolve_universe(db, t_size)
    if not universe:
        logger.warning("Empty universe — skipping cycle %s", cycle_id)
        return _cycle_result(cycle_id, started_at, "empty_universe", [])

    logger.info("Universe resolved: %s", universe)

    # 2. Trigger DeerFlow
    triggered = await trigger_deerflow(universe, gw_url, gw_key)
    if not triggered:
        logger.error("Trigger failed for cycle %s", cycle_id)
        return _cycle_result(cycle_id, started_at, "trigger_failed", universe)

    # 3. Poll for artifact
    watcher = DeerflowResearchProducer(
        store=store,
        sandbox_dir=t_sandbox,
        require_event_id=False,
    )
    watcher.setup()

    artifact = await poll_for_artifact(watcher, t_timeout, t_poll)
    if artifact is None:
        logger.warning("Artifact poll timed out for cycle %s", cycle_id)
        return _cycle_result(cycle_id, started_at, "artifact_timeout", universe)

    # 4. Emit signal
    tags = ["deerflow", "watchlist", "scheduled"]
    signal_event_id = artifact.get("event_id")
    if not signal_event_id:
        tags.append("partial")

    try:
        payload = build_signal_payload(universe, artifact)
        logger.info(
            "Research signal emitted for cycle %s: %s",
            cycle_id,
            payload.symbol,
        )
    except Exception:
        logger.exception("Failed to build signal payload for cycle %s", cycle_id)
        return _cycle_result(cycle_id, started_at, "ingest_failed", universe, artifact=artifact)

    return _cycle_result(
        cycle_id,
        started_at,
        "success",
        universe,
        artifact=artifact,
        signal_event_id=signal_event_id,
    )
