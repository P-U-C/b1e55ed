"""b1e55ed dashboard — FastAPI + Jinja2 + HTMX.

Hashcash lineage precedes Bitcoin (1997). The code remembers.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

_HERE = Path(__file__).resolve().parent

app = FastAPI(title="b1e55ed dashboard", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=_HERE / "static"), name="static")

templates = Jinja2Templates(directory=_HERE / "templates")


# ── Mock data (replaced with real services in Sprint 3B wiring) ──────

MOCK_POSITIONS = [
    {
        "id": "HL-001",
        "symbol": "HYPE",
        "direction": "long",
        "current": 30.63,
        "entry": 31.14,
        "stop": 28.00,
        "target": 36.00,
        "pnl_pct": -1.6,
        "pnl_usd": -51,
        "leverage": 10,
        "leverage_warning": True,
        "near_stop": False,
    }
]

MOCK_CONVICTIONS = [
    {"symbol": "BTC", "magnitude": 7.2, "direction": "long"},
    {"symbol": "HYPE", "magnitude": 5.8, "direction": "long"},
    {"symbol": "ETH", "magnitude": 2.9, "direction": "neutral"},
    {"symbol": "SOL", "magnitude": 4.5, "direction": "long"},
    {"symbol": "SUI", "magnitude": 3.1, "direction": "neutral"},
]

MOCK_WEIGHTS = [
    {"name": "On-chain", "pct": 30},
    {"name": "TradFi", "pct": 23},
    {"name": "Sentiment", "pct": 19},
    {"name": "Technical", "pct": 10},
    {"name": "Events", "pct": 10},
    {"name": "Social", "pct": 8},
]

MOCK_SIGNALS = [
    {"ts": "15:01", "domain": "ta", "asset": "BTC", "desc": "RSI 24 oversold", "direction": "▼", "score": 8.2},
    {"ts": "15:01", "domain": "tradfi", "asset": "BTC", "desc": "Basis 2.4% unwound", "direction": "→", "score": 3.1},
    {"ts": "15:01", "domain": "onchain", "asset": "SOL", "desc": "Smart money +$54K", "direction": "▲", "score": 5.0},
    {"ts": "14:13", "domain": "aci", "asset": "HYPE", "desc": "Consensus +3.33 (high dispersion)", "direction": "→", "score": 4.0},
    {"ts": "09:01", "domain": "events", "asset": "BTC", "desc": "BlackRock ETH staking ETF filed", "direction": "▲", "score": 6.0},
]


# ── Routes ───────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def brain_overview(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "brain.html",
        {
            "request": request,
            "active_page": "brain",
            # Regime
            "regime": "transition",
            "regime_class": "transition",
            "regime_name": "TRANSITION",
            "regime_desc": "No clear trend",
            "regime_confidence": "—",
            # Positions
            "positions": MOCK_POSITIONS,
            "positions_age": "30s ago",
            # Conviction
            "convictions": MOCK_CONVICTIONS,
            "conviction_age": "3m ago",
            "domain_weights": MOCK_WEIGHTS,
            # Signals
            "signals": MOCK_SIGNALS,
            "total_signals": 142,
            # System
            "kill_switch_level": 0,
            "cycle_age": "3m ago",
            "cycle_age_min": 3,
            "producers_healthy": 11,
            "producers_total": 13,
            "events_today": 142,
            "db_size": "24 MB",
            "uptime": "4d 12h",
            "karma_pending": "$2.40",
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=5051)
