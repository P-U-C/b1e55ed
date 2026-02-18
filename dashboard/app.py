"""b1e55ed dashboard — FastAPI + Jinja2 + HTMX.

Hashcash lineage precedes Bitcoin (1997). The code remembers.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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


# ── Routes (mock wiring for visual iteration) ─────────────────────────


def _shell(request: Request, active_page: str) -> dict:
    return {
        "request": request,
        "active_page": active_page,
        "kill_switch_level": 0,
        "regime": "transition",
    }


@app.get("/home", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("home.html", {**_shell(request, "brain")})


@app.get("/", response_class=HTMLResponse)
async def brain_overview(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "brain.html",
        {
            **_shell(request, "brain"),
            # Regime
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


@app.get("/positions", response_class=HTMLResponse)
async def positions_page(request: Request, view: str = "open") -> HTMLResponse:
    return templates.TemplateResponse(
        "positions.html",
        {
            **_shell(request, "positions"),
            "view": view,
            "positions": MOCK_POSITIONS if view == "open" else [],
        },
    )


@app.get("/signals", response_class=HTMLResponse)
async def signals_page(request: Request, domain: str | None = None) -> HTMLResponse:
    domains = [
        {"id": "ta", "label": "TA"},
        {"id": "tradfi", "label": "TradFi"},
        {"id": "onchain", "label": "Onchain"},
        {"id": "social", "label": "Social"},
        {"id": "sentiment", "label": "Sentiment"},
        {"id": "events", "label": "Events"},
        {"id": "aci", "label": "ACI"},
    ]
    filtered = [s for s in MOCK_SIGNALS if (domain is None or s["domain"] == domain)]
    groups = []
    for d in {s["domain"] for s in MOCK_SIGNALS}:
        groups.append(
            {
                "domain": d,
                "age": "—",
                "signals": [s for s in MOCK_SIGNALS if s["domain"] == d][:4],
            }
        )

    return templates.TemplateResponse(
        "signals.html",
        {
            **_shell(request, "signals"),
            "domains": domains,
            "active_domain": domain,
            "signals": filtered,
            "total_signals": 142,
            "domain_groups": groups,
        },
    )


@app.get("/social", response_class=HTMLResponse)
async def social_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "social.html",
        {
            **_shell(request, "social"),
            "pipeline_active": True,
            "pipeline_last_run": "12m ago",
            "llm_cost": 14.20,
            "llm_budget": 100,
            "llm_cost_pct": 14.2,
            "social_kill": False,
            "sources_brief": [
                {"name": "Reddit", "ok": True},
                {"name": "Farcaster", "ok": True},
                {"name": "TikTok", "ok": False},
                {"name": "Telegram", "ok": True},
                {"name": "Polymarket", "ok": True},
                {"name": "Trends", "ok": True},
            ],
            "sentiment_age": "12m ago",
            "sources_active": 6,
            "sentiments": [
                {"symbol": "BTC", "score": 0.6, "label": "bullish lean"},
                {"symbol": "HYPE", "score": 0.8, "label": "bullish"},
                {"symbol": "ETH", "score": -0.2, "label": "neutral/bear"},
                {"symbol": "SOL", "score": 0.5, "label": "bullish lean"},
                {"symbol": "SUI", "score": -0.1, "label": "neutral"},
            ],
            "alerts": [
                {
                    "type": "echo_chamber",
                    "token": "$KIMCHI",
                    "desc": "4 sources, same narrative within 2h. Likely coordinated. Fade signal.",
                },
                {
                    "type": "velocity",
                    "token": "$BUTTCOIN",
                    "desc": "Mentions 3x in 1h. Early buzz, no on-chain confirmation yet.",
                },
                {
                    "type": "divergence",
                    "token": "$VIRTUAL",
                    "desc": "Social buzz up 40% but on-chain flow flat. Pump fake probability: high.",
                },
            ],
            "narratives": [
                {"name": "AI agents", "velocity": 85, "stage": "mature", "age": "47d"},
                {"name": "RWA / tokenization", "velocity": 65, "stage": "growing", "age": "23d"},
                {"name": "BTC ETF staking", "velocity": 50, "stage": "early", "age": "3d"},
                {"name": "Solana memecoins", "velocity": 40, "stage": "fading", "age": "62d"},
                {"name": "L2 fee wars", "velocity": 30, "stage": "early", "age": "8d"},
            ],
            "curator_signals": [
                {"ts": "15:12", "source": "zoz", "asset": "HYPE", "desc": "Team hinting at new perp listings", "score": 7.0},
                {"ts": "14:30", "source": "auto", "asset": "BTC", "desc": "Reddit sentiment neutral, volume declining", "score": 4.0},
                {"ts": "13:45", "source": "auto", "asset": "SOL", "desc": "Farcaster dev mentions +22%", "score": 5.0},
                {"ts": "12:00", "source": "zoz", "asset": "ETH", "desc": "Staking ETF is structural, not speculative", "score": 8.0},
            ],
            "sources": [
                {"name": "Reddit", "status": "ok", "last_hit": "12m", "signals_24h": 34, "quality": 0.72},
                {"name": "Farcaster", "status": "ok", "last_hit": "12m", "signals_24h": 18, "quality": 0.65},
                {"name": "TikTok", "status": "down", "last_hit": "3d", "signals_24h": 0, "quality": None},
                {"name": "Telegram", "status": "ok", "last_hit": "45m", "signals_24h": 8, "quality": 0.70},
                {"name": "Polymarket", "status": "ok", "last_hit": "12m", "signals_24h": 12, "quality": 0.81},
                {"name": "Trends", "status": "ok", "last_hit": "6h", "signals_24h": 4, "quality": 0.58},
                {"name": "Nitter/X", "status": "down", "last_hit": "—", "signals_24h": 0, "quality": None},
            ],
            "source_warnings": ["Apify: ⚠ Monthly limit exceeded (resets in 12d)"],
        },
    )


@app.get("/performance", response_class=HTMLResponse)
async def performance_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "performance.html",
        {
            **_shell(request, "performance"),
            "total_trades": 0,
            "total_pnl": 0,
        },
    )


@app.get("/system", response_class=HTMLResponse)
async def system_page(request: Request) -> HTMLResponse:
    producers = [
        {"name": "ta-indicators", "domain": "ta", "health": "ok", "last_run": "3m"},
        {"name": "orderbook-depth", "domain": "tradfi", "health": "ok", "last_run": "3m"},
        {"name": "price-alerts", "domain": "price", "health": "ok", "last_run": "3m"},
        {"name": "tradfi-basis", "domain": "tradfi", "health": "ok", "last_run": "3m"},
        {"name": "etf-flows", "domain": "etf", "health": "ok", "last_run": "3m"},
        {"name": "onchain-flows", "domain": "onchain", "health": "error", "last_run": "6h"},
        {"name": "stablecoin", "domain": "onchain", "health": "error", "last_run": "6h"},
        {"name": "whale-tracking", "domain": "onchain", "health": "error", "last_run": "6h"},
        {"name": "market-events", "domain": "events", "health": "ok", "last_run": "3m"},
        {"name": "market-sentiment", "domain": "sentiment", "health": "ok", "last_run": "3m"},
        {"name": "social-buzz", "domain": "social", "health": "ok", "last_run": "12m"},
        {"name": "curator-ingest", "domain": "curator", "health": "ok", "last_run": "12m"},
        {"name": "aci", "domain": "aci", "health": "ok", "last_run": "3m"},
    ]
    resources = [
        {"name": "Disk", "bar": True, "pct": 31, "detail": "31%", "warning": False},
        {"name": "Nansen", "bar": False, "detail": "1,080/1,100 remaining", "warning": False},
        {"name": "Allium", "bar": False, "detail": "401 (subscription expired)", "warning": True},
        {"name": "Brave", "bar": False, "detail": "~1,800/2,000 remaining", "warning": False},
    ]
    return templates.TemplateResponse(
        "system.html",
        {
            **_shell(request, "system"),
            "producers": producers,
            "producers_healthy": 11,
            "producers_total": 13,
            "kill_switch_level": 0,
            "kill_switch_label": "NORMAL",
            "events_total": 1247,
            "events_today": 142,
            "db_size": "24 MB",
            "hash_chain_ok": True,
            "event_breakdown": [
                {"type": "signal", "count": 128},
                {"type": "brain", "count": 8},
                {"type": "execution", "count": 4},
                {"type": "sys", "count": 2},
            ],
            "resources": resources,
            "uptime": "4d 12h 33m",
        },
    )


@app.get("/config", response_class=HTMLResponse)
async def config_page(request: Request) -> HTMLResponse:
    cfg = {
        "risk": {
            "max_daily_loss_usd": 1000,
            "max_position_size_pct": 15,
            "max_leverage_default": 5,
            "max_leverage_crisis": 1,
        },
        "brain": {
            "cycle_interval_s": 300,
            "min_conviction": 65,
            "cts_auto_trigger": 75,
            "synthesis_version": "v2 (locked)",
        },
        "execution": {
            "mode": "paper",
            "confirm_threshold_usd": 500,
            "circuit_min_s": 10,
            "circuit_max_s": 60,
        },
        "karma": {"enabled": True, "pct": 0.5, "mode": "manual", "treasury": "0xPUC…"},
    }
    return templates.TemplateResponse(
        "config.html",
        {
            **_shell(request, "config"),
            "preset": "balanced",
            "presets": ["conservative", "balanced", "degen"],
            "cfg": cfg,
        },
    )


@app.get("/treasury", response_class=HTMLResponse)
async def treasury_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "treasury.html",
        {
            **_shell(request, "treasury"),
            "intents": [],
            "receipts": [],
            "karma_rate": "0.5% of profit",
            "karma_mode": "manual",
            "karma_threshold": "$50",
            "treasury_addr": "0xPUC…",
            "pending_amount": "$0",
            "lifetime_earned": "$0",
            "settled_amount": "$0",
            "receipts_count": 0,
        },
    )


@app.get("/partials/kill-dot", response_class=HTMLResponse)
async def kill_dot(request: Request) -> HTMLResponse:
    # keep nav alive for visual; replace with real API later
    html = (
        '<div class="kill-dot level-0" title="Kill switch: level 0" '
        'hx-get="/partials/kill-dot" hx-trigger="every 30s" hx-swap="outerHTML"></div>'
    )
    return HTMLResponse(html)


@app.get("/partials/regime-pill", response_class=HTMLResponse)
async def regime_pill(request: Request) -> HTMLResponse:
    html = (
        '<span class="regime-pill regime-transition" '
        'hx-get="/partials/regime-pill" hx-trigger="every 30s" hx-swap="outerHTML">'
        'TRANSITION</span>'
    )
    return HTMLResponse(html)


@app.get("/partials/regime-banner", response_class=HTMLResponse)
async def regime_banner(request: Request) -> HTMLResponse:
    html = (
        '<div class="regime-banner transition">'
        '<span class="regime-name">TRANSITION</span>'
        '<span class="regime-desc">No clear trend</span>'
        '<span class="regime-confidence">—</span>'
        '</div>'
    )
    return HTMLResponse(html)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=5051)
