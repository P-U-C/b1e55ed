"""api.routes.metrics

Prometheus-format metrics stub endpoint.

Returns a text/plain response in the standard Prometheus exposition format.
Does not require a full prometheus_client integration — computed on-demand
from the database.

Endpoint: GET /metrics

Prometheus was named by engineers at SoundCloud in 2012. The monitoring
system was a joke at first — named after the god who stole fire from the
heavens, because they were stealing metrics from their infrastructure.
The exposition format became an industry standard. The original system
was retired years ago. The format survived.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from starlette.responses import PlainTextResponse

from api.deps import get_db
from engine.core.database import Database

router = APIRouter()


def _prom_line(name: str, value: int | float, help_text: str = "", metric_type: str = "gauge") -> str:
    lines = []
    if help_text:
        lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} {metric_type}")
    lines.append(f"{name} {value}")
    return "\n".join(lines)


@router.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics(db: Database = Depends(get_db)) -> PlainTextResponse:
    """Prometheus-format metrics for scraping.

    Metrics exposed:
    - b1e55ed_contributors_total
    - b1e55ed_brain_cycles_total
    - b1e55ed_karma_intents_total
    - b1e55ed_karma_settled_total
    - b1e55ed_signals_total
    - b1e55ed_positions_total
    """
    lines: list[str] = []

    # contributors total
    try:
        r = db.fetchone("SELECT COUNT(1) FROM contributors")
        contributors_total = int(r[0]) if r else 0
    except Exception:
        contributors_total = 0
    lines.append(_prom_line("b1e55ed_contributors_total", contributors_total, "Total registered contributors", "gauge"))

    # brain cycles total (from events)
    try:
        r = db.fetchone("SELECT COUNT(1) FROM events WHERE type = 'brain.cycle.v1'")
        brain_cycles_total = int(r[0]) if r else 0
    except Exception:
        brain_cycles_total = 0
    lines.append(_prom_line("b1e55ed_brain_cycles_total", brain_cycles_total, "Total brain cycle events recorded", "counter"))

    # karma intents total
    try:
        r = db.fetchone("SELECT COUNT(1) FROM karma_intents")
        karma_intents_total = int(r[0]) if r else 0
    except Exception:
        karma_intents_total = 0
    lines.append(_prom_line("b1e55ed_karma_intents_total", karma_intents_total, "Total karma intents created", "counter"))

    # karma settled total
    try:
        r = db.fetchone("SELECT COUNT(1) FROM karma_intents WHERE settled = 1")
        karma_settled_total = int(r[0]) if r else 0
    except Exception:
        karma_settled_total = 0
    lines.append(_prom_line("b1e55ed_karma_settled_total", karma_settled_total, "Total karma intents settled", "counter"))

    # signals total (signal.* events)
    try:
        r = db.fetchone("SELECT COUNT(1) FROM events WHERE type LIKE 'signal.%'")
        signals_total = int(r[0]) if r else 0
    except Exception:
        signals_total = 0
    lines.append(_prom_line("b1e55ed_signals_total", signals_total, "Total signal events recorded", "counter"))

    # positions total
    try:
        r = db.fetchone("SELECT COUNT(1) FROM positions")
        positions_total = int(r[0]) if r else 0
    except Exception:
        positions_total = 0
    lines.append(_prom_line("b1e55ed_positions_total", positions_total, "Total positions recorded", "gauge"))

    # requests from rate limiter window (best-effort)
    try:
        r = db.fetchone("SELECT COALESCE(SUM(request_count), 0) FROM rate_limit_windows")
        requests_total = int(r[0]) if r else 0
    except Exception:
        requests_total = 0
    lines.append(_prom_line("b1e55ed_requests_total", requests_total, "Total API requests recorded by rate limiter", "counter"))

    output = "\n".join(lines) + "\n"
    return PlainTextResponse(content=output, media_type="text/plain; version=0.0.4")
