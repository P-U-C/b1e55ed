"""Social intelligence API routes.

Pipeline diagnostics, sentiment data, alerts, curator feed, watchlist and
source configuration.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.auth import AuthDep
from api.deps import get_db
from engine.core.database import Database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/social", dependencies=[AuthDep])


# ---------------------------------------------------------------------------
# DB helpers — ensure social tables exist
# ---------------------------------------------------------------------------


def _ensure_social_watchlist(db: Database) -> None:
    with db.conn:
        db.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS social_watchlist (
                symbol TEXT PRIMARY KEY,
                added_at TEXT NOT NULL
            )
            """
        )


def _ensure_social_sources(db: Database) -> None:
    with db.conn:
        db.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS social_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                value TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                added_at TEXT NOT NULL
            )
            """
        )


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ProducerInfo(BaseModel):
    name: str
    consecutive_failures: int = 0
    last_run_at: str | None = None
    last_success_at: str | None = None
    last_error: str | None = None
    events_produced: int = 0
    healthy: bool = False


class StatusResponse(BaseModel):
    pipeline_active: bool
    pipeline_status: str
    producers: list[ProducerInfo]
    watchlist: list[str]
    watchlist_count: int
    sources_configured: int
    seeded: bool
    diagnosis: str
    actions_available: list[str]


class SentimentItem(BaseModel):
    symbol: str
    score: float = 0.0
    direction: str = "neutral"
    label: str = "Neutral"
    source_count: int = 0
    ts: str = ""


class SentimentResponse(BaseModel):
    items: list[SentimentItem]
    empty_reason: str | None = None


class AlertItem(BaseModel):
    symbol: str = ""
    type: str = ""
    desc: str = ""
    ts: str = ""


class AlertsResponse(BaseModel):
    items: list[AlertItem]


class NarrativeItem(BaseModel):
    name: str = ""
    velocity: float = 0.0
    stage: str = ""
    age: str = ""


class NarrativesResponse(BaseModel):
    items: list[NarrativeItem]
    message: str = ""


class SourceItem(BaseModel):
    id: int = 0
    name: str = ""
    type: str = ""
    value: str = ""
    enabled: bool = True
    added_at: str = ""


class SourcesResponse(BaseModel):
    items: list[SourceItem]


class CuratorItem(BaseModel):
    symbol: str = ""
    direction: str = ""
    conviction: float = 0.0
    rationale: str = ""
    source: str = ""
    ts: str = ""
    # Legacy fields dashboard might use
    asset: str = ""
    desc: str = ""
    score: float = 0.0


class CuratorResponse(BaseModel):
    items: list[CuratorItem]


class SeedRequest(BaseModel):
    watchlist: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL", "HYPE", "SUI"])


class SeedResponse(BaseModel):
    seeded: bool
    count: int


class ResetResponse(BaseModel):
    reset: bool
    producers_reset: int


class RunNowResponse(BaseModel):
    triggered: bool
    message: str


class AddWatchlistRequest(BaseModel):
    symbol: str


class AddWatchlistResponse(BaseModel):
    added: bool
    symbol: str


class AddSourceRequest(BaseModel):
    name: str
    type: str
    value: str


class AddSourceResponse(BaseModel):
    added: bool
    id: int


# ---------------------------------------------------------------------------
# GET endpoints
# ---------------------------------------------------------------------------


@router.get("/status", response_model=StatusResponse)
def social_status(db: Database = Depends(get_db)) -> StatusResponse:
    """Pipeline diagnostic — shows why social is up/down and what actions help."""
    _ensure_social_watchlist(db)
    _ensure_social_sources(db)

    # Query social producers
    rows = db.conn.execute(
        """
        SELECT name, consecutive_failures, last_run_at, last_success_at,
               last_error, events_produced
        FROM producer_health
        WHERE domain = 'social'
        """
    ).fetchall()

    producers: list[ProducerInfo] = []
    for r in rows:
        cf = int(r[1]) if r[1] is not None else 0
        producers.append(
            ProducerInfo(
                name=str(r[0]),
                consecutive_failures=cf,
                last_run_at=str(r[2]) if r[2] else None,
                last_success_at=str(r[3]) if r[3] else None,
                last_error=str(r[4]) if r[4] else None,
                events_produced=int(r[5]) if r[5] is not None else 0,
                healthy=cf < 3 and r[4] is None,
            )
        )

    # Watchlist
    wl_rows = db.conn.execute("SELECT symbol FROM social_watchlist ORDER BY symbol").fetchall()
    watchlist = [str(r[0]) for r in wl_rows]
    watchlist_count = len(watchlist)
    seeded = watchlist_count > 0

    # Sources
    src_count = db.conn.execute("SELECT COUNT(*) FROM social_sources WHERE enabled = 1").fetchone()[0]
    sources_configured = int(src_count) if src_count else 0

    # Pipeline status
    pipeline_active = any(p.consecutive_failures < 3 for p in producers) if producers else False
    all_quarantined = all(p.consecutive_failures >= 5 for p in producers) if producers else False

    # Diagnosis
    if not seeded:
        diagnosis = "Watchlist not seeded — no tokens to monitor"
        pipeline_status = "unconfigured"
    elif not producers:
        diagnosis = "No social producers registered"
        pipeline_status = "unconfigured"
    elif all_quarantined:
        max_failures = max(p.consecutive_failures for p in producers)
        diagnosis = f"All producers quarantined ({max_failures} consecutive failures)"
        pipeline_status = "down"
    elif pipeline_active:
        diagnosis = "Running"
        pipeline_status = "active"
    else:
        diagnosis = "Some producers failing — pipeline degraded"
        pipeline_status = "degraded"

    # Actions
    actions: list[str] = ["run_now"]
    if not seeded:
        actions.insert(0, "seed_default_watchlist")
    if any(p.consecutive_failures > 0 for p in producers):
        actions.append("reset_failures")

    return StatusResponse(
        pipeline_active=pipeline_active,
        pipeline_status=pipeline_status,
        producers=producers,
        watchlist=watchlist,
        watchlist_count=watchlist_count,
        sources_configured=sources_configured,
        seeded=seeded,
        diagnosis=diagnosis,
        actions_available=actions,
    )


@router.get("/sentiment", response_model=SentimentResponse)
def social_sentiment(db: Database = Depends(get_db)) -> SentimentResponse:
    """Sentiment data from social signal events."""
    rows = db.conn.execute(
        """
        SELECT payload, ts FROM events
        WHERE type = 'signal.social.v1'
        ORDER BY ts DESC
        LIMIT 50
        """
    ).fetchall()

    if not rows:
        return SentimentResponse(
            items=[],
            empty_reason="No pipeline runs yet — seed watchlist and run pipeline",
        )

    # Deduplicate by symbol, keep latest
    seen: dict[str, SentimentItem] = {}
    for r in rows:
        payload = _safe_json(r[0])
        symbol = str(payload.get("symbol") or payload.get("asset") or payload.get("token") or "")
        if not symbol or symbol in seen:
            continue
        score = float(payload.get("score") or 0.0)
        direction = str(payload.get("direction") or "neutral")
        label = direction.capitalize() if direction else "Neutral"
        seen[symbol] = SentimentItem(
            symbol=symbol,
            score=score,
            direction=direction,
            label=label,
            source_count=int(payload.get("source_count") or 0),
            ts=str(r[1] or ""),
        )

    return SentimentResponse(items=list(seen.values())[:20])


@router.get("/alerts", response_model=AlertsResponse)
def social_alerts(db: Database = Depends(get_db)) -> AlertsResponse:
    """Echo chamber and velocity alerts from social events."""
    rows = db.conn.execute(
        """
        SELECT payload, ts FROM events
        WHERE type = 'signal.social.v1'
        ORDER BY ts DESC
        LIMIT 100
        """
    ).fetchall()

    items: list[AlertItem] = []
    for r in rows:
        payload = _safe_json(r[0])
        echo = payload.get("echo_chamber_flag")
        contrarian = payload.get("contrarian_flag")
        if echo or contrarian:
            alert_type = "echo_chamber" if echo else "contrarian"
            symbol = str(payload.get("symbol") or payload.get("asset") or "")
            desc = str(payload.get("desc") or payload.get("description") or f"{alert_type} detected for {symbol}")
            items.append(
                AlertItem(
                    symbol=symbol,
                    type=alert_type,
                    desc=desc,
                    ts=str(r[1] or ""),
                )
            )

    return AlertsResponse(items=items[:20])


@router.get("/narratives", response_model=NarrativesResponse)
def social_narratives(db: Database = Depends(get_db)) -> NarrativesResponse:
    """Narrative tracking — returns existing narrative events or helpful empty state."""
    rows = db.conn.execute(
        """
        SELECT payload, ts FROM events
        WHERE type = 'signal.narrative.v1'
        ORDER BY ts DESC
        LIMIT 20
        """
    ).fetchall()

    items: list[NarrativeItem] = []
    for r in rows:
        payload = _safe_json(r[0])
        items.append(
            NarrativeItem(
                name=str(payload.get("name") or payload.get("narrative") or ""),
                velocity=float(payload.get("velocity") or 0.0),
                stage=str(payload.get("stage") or ""),
                age=str(payload.get("age") or ""),
            )
        )

    msg = ""
    if not items:
        msg = "Narrative tracking will populate as the pipeline detects emerging market themes from social signals."

    return NarrativesResponse(items=items, message=msg)


@router.get("/sources", response_model=SourcesResponse)
def social_sources(db: Database = Depends(get_db)) -> SourcesResponse:
    """Configured social sources (twitter accounts, keywords, etc.)."""
    _ensure_social_sources(db)

    rows = db.conn.execute("SELECT id, name, type, value, enabled, added_at FROM social_sources ORDER BY id").fetchall()

    items = [
        SourceItem(
            id=int(r[0]),
            name=str(r[1]),
            type=str(r[2]),
            value=str(r[3]),
            enabled=bool(r[4]),
            added_at=str(r[5]),
        )
        for r in rows
    ]

    return SourcesResponse(items=items)


@router.get("/curator-feed", response_model=CuratorResponse)
def curator_feed(db: Database = Depends(get_db)) -> CuratorResponse:
    """Curator signals from the events table."""
    rows = db.conn.execute(
        """
        SELECT payload, ts, source FROM events
        WHERE type = 'signal.curator.v1'
        ORDER BY ts DESC
        LIMIT 50
        """
    ).fetchall()

    items: list[CuratorItem] = []
    for r in rows:
        payload = _safe_json(r[0])
        symbol = str(payload.get("symbol") or payload.get("asset") or payload.get("token") or "")
        direction = str(payload.get("direction") or "")
        conviction = float(payload.get("conviction") or payload.get("score") or 0.0)
        rationale = str(payload.get("rationale") or payload.get("desc") or payload.get("description") or "")
        source = str(r[2] or payload.get("source") or "")

        items.append(
            CuratorItem(
                symbol=symbol,
                direction=direction,
                conviction=conviction,
                rationale=rationale,
                source=source,
                ts=str(r[1] or ""),
                # Legacy fields for dashboard compat
                asset=symbol,
                desc=rationale,
                score=conviction,
            )
        )

    return CuratorResponse(items=items)


@router.get("/watchlist")
def get_watchlist(db: Database = Depends(get_db)) -> dict[str, Any]:
    """Current watchlist tokens."""
    _ensure_social_watchlist(db)
    rows = db.conn.execute("SELECT symbol, added_at FROM social_watchlist ORDER BY symbol").fetchall()
    return {
        "items": [{"symbol": str(r[0]), "added_at": str(r[1])} for r in rows],
        "count": len(rows),
    }


# ---------------------------------------------------------------------------
# POST endpoints (actions)
# ---------------------------------------------------------------------------


@router.post("/seed", response_model=SeedResponse)
def seed_watchlist(body: SeedRequest, db: Database = Depends(get_db)) -> SeedResponse:
    """Seed default watchlist tokens."""
    _ensure_social_watchlist(db)
    now = datetime.now(tz=UTC).isoformat()

    count = 0
    with db.conn:
        for symbol in body.watchlist:
            s = symbol.strip().upper()
            if not s:
                continue
            existing = db.conn.execute("SELECT symbol FROM social_watchlist WHERE symbol = ?", (s,)).fetchone()
            if existing is None:
                db.conn.execute(
                    "INSERT INTO social_watchlist (symbol, added_at) VALUES (?, ?)",
                    (s, now),
                )
                count += 1

    return SeedResponse(seeded=True, count=count)


@router.post("/reset-failures", response_model=ResetResponse)
def reset_failures(db: Database = Depends(get_db)) -> ResetResponse:
    """Reset consecutive failure counts for social producers."""
    with db.conn:
        cur = db.conn.execute(
            """
            UPDATE producer_health
            SET consecutive_failures = 0, last_error = NULL
            WHERE domain = 'social'
            """
        )

    return ResetResponse(reset=True, producers_reset=cur.rowcount)


@router.post("/run-now", response_model=RunNowResponse)
def run_now(db: Database = Depends(get_db)) -> RunNowResponse:
    """Trigger an immediate social pipeline run (best-effort)."""
    # Reset quarantine so producers can run
    with db.conn:
        db.conn.execute(
            """
            UPDATE producer_health
            SET quarantined_until = NULL, quarantined_reason = NULL
            WHERE domain = 'social'
            """
        )

    # Best-effort: try to invoke the producer via registry
    try:
        from engine.producers import registry

        names = registry.list_producers()
        social_producers = [n for n in names if "social" in n.lower() or "sentiment" in n.lower()]
        if social_producers:
            return RunNowResponse(
                triggered=True,
                message=f"Quarantine cleared for social producers. Next scheduler tick will run: {', '.join(social_producers)}",
            )
    except Exception:
        pass

    return RunNowResponse(
        triggered=True,
        message="Social producer quarantine cleared. Producers will run on next scheduler tick.",
    )


@router.post("/watchlist/add", response_model=AddWatchlistResponse)
def add_to_watchlist(body: AddWatchlistRequest, db: Database = Depends(get_db)) -> AddWatchlistResponse:
    """Add a token to the social watchlist."""
    _ensure_social_watchlist(db)
    symbol = body.symbol.strip().upper()
    now = datetime.now(tz=UTC).isoformat()

    existing = db.conn.execute("SELECT symbol FROM social_watchlist WHERE symbol = ?", (symbol,)).fetchone()
    if existing is not None:
        return AddWatchlistResponse(added=False, symbol=symbol)

    with db.conn:
        db.conn.execute(
            "INSERT INTO social_watchlist (symbol, added_at) VALUES (?, ?)",
            (symbol, now),
        )

    return AddWatchlistResponse(added=True, symbol=symbol)


@router.post("/sources/add", response_model=AddSourceResponse)
def add_source(body: AddSourceRequest, db: Database = Depends(get_db)) -> AddSourceResponse:
    """Add a social data source."""
    _ensure_social_sources(db)
    now = datetime.now(tz=UTC).isoformat()

    with db.conn:
        cur = db.conn.execute(
            "INSERT INTO social_sources (name, type, value, enabled, added_at) VALUES (?, ?, ?, 1, ?)",
            (body.name, body.type, body.value, now),
        )

    return AddSourceResponse(added=True, id=cur.lastrowid or 0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_json(raw: Any) -> dict[str, Any]:
    """Parse a JSON string or return empty dict."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        val = json.loads(str(raw))
        return val if isinstance(val, dict) else {}
    except Exception:
        return {}
