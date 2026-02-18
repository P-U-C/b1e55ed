"""b1e55ed dashboard — FastAPI + Jinja2 + HTMX.

Hashcash lineage precedes Bitcoin (1997). The code remembers.
"""

from __future__ import annotations

import contextlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from dashboard.services.api_client import ApiClient

_HERE = Path(__file__).resolve().parent

app = FastAPI(title="b1e55ed dashboard", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=_HERE / "static"), name="static")

templates = Jinja2Templates(directory=_HERE / "templates")


@app.on_event("startup")
def _startup() -> None:
    base_url = os.getenv("B1E55ED_API_BASE_URL", "http://127.0.0.1:5050")
    token = os.getenv("B1E55ED_API_TOKEN")
    app.state.api_client = ApiClient(base_url=base_url, token=token)


def _api(request: Request) -> ApiClient:
    return request.app.state.api_client


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)


def _age_str(ts: datetime | None) -> tuple[str, int]:
    if ts is None:
        return "never", 10**9
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    delta = _now_utc() - ts
    mins = int(delta.total_seconds() // 60)
    if mins < 1:
        return "<1m ago", 0
    if mins < 60:
        return f"{mins}m ago", mins
    hrs = mins // 60
    return f"{hrs}h ago", mins


def _shell(request: Request, active_page: str, *, kill_switch_level: int = 0, regime: str | None = None) -> dict[str, Any]:
    return {
        "request": request,
        "active_page": active_page,
        "kill_switch_level": kill_switch_level,
        "regime": regime or "transition",
    }


def _map_positions(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []

    out: list[dict[str, Any]] = []
    for p in raw:
        if not isinstance(p, dict):
            continue
        entry = float(p.get("entry_price") or 0.0)
        stop = float(p.get("stop_loss") or entry)
        target = float(p.get("take_profit") or entry)
        leverage = float(p.get("leverage") or 1.0)

        out.append(
            {
                "id": str(p.get("id") or "—"),
                "symbol": str(p.get("asset") or p.get("symbol") or "—"),
                "direction": str(p.get("direction") or "neutral"),
                # API currently doesn't expose mark price / pnl; keep UI stable with safe defaults.
                "current": entry,
                "entry": entry,
                "stop": stop,
                "target": target,
                "pnl_pct": float(p.get("pnl_pct") or 0.0),
                "pnl_usd": float(p.get("realized_pnl") or 0.0),
                "leverage": leverage,
                "leverage_warning": False,
                "near_stop": False,
                "opened": None,
                "conviction_entry": p.get("conviction_id"),
                "conviction_current": None,
                "regime_entry": p.get("regime_at_entry"),
                "held": None,
                "status": p.get("status"),
            }
        )
    return out


def _domain_from_type(t: str) -> str:
    # event type like signal.ta.rsi.v1
    parts = t.split(".")
    if len(parts) >= 2 and parts[0] == "signal":
        return parts[1]
    return parts[1] if len(parts) >= 2 else "unknown"


def _map_signals(resp: Any) -> list[dict[str, Any]]:
    if not isinstance(resp, dict):
        return []
    items = resp.get("items")
    if not isinstance(items, list):
        return []

    out: list[dict[str, Any]] = []
    for s in items:
        if not isinstance(s, dict):
            continue
        payload = s.get("payload") if isinstance(s.get("payload"), dict) else {}
        t = str(s.get("type") or "")
        domain = _domain_from_type(t)

        ts = s.get("ts")
        ts_hm = "—"
        try:
            # API returns ISO string
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            ts_hm = dt.strftime("%H:%M")
        except Exception:
            ts_hm = "—"

        asset = payload.get("asset") or payload.get("symbol") or payload.get("token") or "—"
        desc = payload.get("desc") or payload.get("description") or payload.get("message") or t
        score = payload.get("score")
        try:
            score_f = float(score) if score is not None else 0.0
        except Exception:
            score_f = 0.0

        direction = payload.get("direction")
        if direction not in {"▲", "▼", "→"}:
            direction = "→"

        out.append(
            {
                "ts": ts_hm,
                "domain": domain,
                "asset": str(asset),
                "desc": str(desc),
                "direction": str(direction),
                "score": score_f,
            }
        )

    return out


def _regime_banner_context(regime_payload: Any, *, stale: bool) -> dict[str, Any]:
    regime = None
    changed_at = None
    conditions: dict[str, Any] = {}
    if isinstance(regime_payload, dict):
        regime = regime_payload.get("regime")
        changed_at = regime_payload.get("changed_at")
        if isinstance(regime_payload.get("conditions"), dict):
            conditions = regime_payload["conditions"]

    regime_name = str(regime or "TRANSITION").upper()
    regime_class = str(regime or "transition")

    confidence = conditions.get("confidence")
    conf_str = "—"
    if confidence is not None:
        try:
            conf_str = f"{float(confidence):.2f}"
        except Exception:
            conf_str = str(confidence)

    desc = conditions.get("desc") or conditions.get("description") or "No clear trend"

    age = "stale" if stale else "—"
    if isinstance(changed_at, str):
        try:
            dt = datetime.fromisoformat(changed_at.replace("Z", "+00:00"))
            age, _ = _age_str(dt)
        except Exception:
            pass

    return {
        "regime_class": regime_class,
        "regime_name": regime_name,
        "regime_desc": str(desc),
        "regime_confidence": conf_str,
        "regime_age": age,
    }


# ---- Page routes -------------------------------------------------------


@app.get("/home", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    # kept for backward-compat with early shell
    return templates.TemplateResponse("home.html", {**_shell(request, "brain")})


@app.get("/", response_class=HTMLResponse)
def brain_overview(request: Request) -> HTMLResponse:
    client = _api(request)

    ks_res = client.get_kill_switch()
    ks_level = 0
    if ks_res.ok and isinstance(ks_res.data, dict):
        try:
            ks_level = int(ks_res.data.get("kill_switch_level") or 0)
        except Exception:
            ks_level = 0

    regime_res = client.get_regime()
    regime_ctx = _regime_banner_context(regime_res.data, stale=not regime_res.ok)

    pos_res = client.get_positions()
    positions = _map_positions(pos_res.data)
    positions_age = "—" if pos_res.ok else "stale"

    sig_res = client.get_signals(domain=None)
    signals = _map_signals(sig_res.data)
    total_signals = sig_res.data.get("total") if (sig_res.ok and isinstance(sig_res.data, dict)) else None

    prod_res = client.get_producers_status()
    producers = prod_res.data.get("producers") if (prod_res.ok and isinstance(prod_res.data, dict)) else {}
    producers_total = len(producers) if isinstance(producers, dict) else 0
    producers_healthy = 0
    if isinstance(producers, dict):
        for v in producers.values():
            if isinstance(v, dict) and v.get("healthy") is True:
                producers_healthy += 1

    cycle_age = "never"
    cycle_age_min = 10**9
    if ks_res.ok and isinstance(ks_res.data, dict):
        last_cycle_at = ks_res.data.get("last_cycle_at")
        if isinstance(last_cycle_at, str):
            try:
                dt = datetime.fromisoformat(last_cycle_at.replace("Z", "+00:00"))
                cycle_age, cycle_age_min = _age_str(dt)
            except Exception:
                pass

    karma_pending = "$0"
    treasury_res = client.get_karma_summary()
    if treasury_res.ok and isinstance(treasury_res.data, dict):
        pending_n = treasury_res.data.get("pending_intents")
        try:
            pending_n = int(pending_n)
        except Exception:
            pending_n = 0
        karma_pending = f"{pending_n} intents"

    return templates.TemplateResponse(
        "brain.html",
        {
            **_shell(request, "brain", kill_switch_level=ks_level, regime=regime_ctx.get("regime_class")),
            **regime_ctx,
            "positions": positions,
            "positions_age": positions_age,
            # Conviction: not wired yet in API; keep empty.
            "convictions": [],
            "conviction_age": "stale",
            "domain_weights": [],
            "signals": signals[:12],
            "total_signals": total_signals or 0,
            "cycle_age": cycle_age,
            "cycle_age_min": cycle_age_min,
            "producers_healthy": producers_healthy,
            "producers_total": producers_total,
            "events_today": 0,
            "db_size": "—",
            "uptime": "—",
            "karma_pending": karma_pending,
        },
    )


@app.get("/positions", response_class=HTMLResponse)
def positions_page(request: Request, view: str = "open") -> HTMLResponse:
    client = _api(request)
    res = client.get_positions()
    all_positions = _map_positions(res.data)

    if view == "closed":
        positions = [p for p in all_positions if str(p.get("status") or "").lower() == "closed"]
    else:
        positions = [p for p in all_positions if str(p.get("status") or "").lower() != "closed"]

    return templates.TemplateResponse(
        "positions.html",
        {
            **_shell(request, "positions"),
            "view": view,
            "positions": positions,
        },
    )


@app.get("/signals", response_class=HTMLResponse)
def signals_page(request: Request, domain: str | None = None) -> HTMLResponse:
    client = _api(request)
    res = client.get_signals(domain=domain)
    signals = _map_signals(res.data)

    # Build latest-by-domain groups from whatever we got.
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for s in signals:
        by_domain.setdefault(str(s.get("domain") or "unknown"), []).append(s)

    domain_groups = []
    for d, items in sorted(by_domain.items()):
        domain_groups.append({"domain": d, "age": "—" if res.ok else "stale", "signals": items[:4]})

    domains = [
        {"id": "ta", "label": "TA"},
        {"id": "tradfi", "label": "TradFi"},
        {"id": "onchain", "label": "Onchain"},
        {"id": "social", "label": "Social"},
        {"id": "sentiment", "label": "Sentiment"},
        {"id": "events", "label": "Events"},
        {"id": "aci", "label": "ACI"},
    ]

    total = res.data.get("total") if (res.ok and isinstance(res.data, dict)) else 0

    return templates.TemplateResponse(
        "signals.html",
        {
            **_shell(request, "signals"),
            "domains": domains,
            "active_domain": domain,
            "signals": signals,
            "total_signals": total,
            "domain_groups": domain_groups,
        },
    )


@app.get("/social", response_class=HTMLResponse)
def social_page(request: Request) -> HTMLResponse:
    client = _api(request)

    sent_res = client.get_social_sentiment()
    alerts_res = client.get_social_alerts()
    nar_res = client.get_social_narratives()
    src_res = client.get_social_sources()
    cur_res = client.get_curator_feed()

    sentiments = sent_res.data.get("items") if (sent_res.ok and isinstance(sent_res.data, dict)) else []
    alerts = alerts_res.data.get("items") if (alerts_res.ok and isinstance(alerts_res.data, dict)) else []
    narratives = nar_res.data.get("items") if (nar_res.ok and isinstance(nar_res.data, dict)) else []
    sources = src_res.data.get("items") if (src_res.ok and isinstance(src_res.data, dict)) else []
    curator_signals = cur_res.data.get("items") if (cur_res.ok and isinstance(cur_res.data, dict)) else []

    return templates.TemplateResponse(
        "social.html",
        {
            **_shell(request, "social"),
            "pipeline_active": sent_res.ok or alerts_res.ok or src_res.ok,
            "pipeline_last_run": "—" if (sent_res.ok or alerts_res.ok) else "stale",
            "llm_cost": 0.0,
            "llm_budget": 100,
            "llm_cost_pct": 0.0,
            "social_kill": False,
            "sources_brief": [],
            "sentiment_age": "—" if sent_res.ok else "stale",
            "sources_active": 0,
            "sentiments": sentiments if isinstance(sentiments, list) else [],
            "alerts": alerts if isinstance(alerts, list) else [],
            "narratives": narratives if isinstance(narratives, list) else [],
            "curator_signals": curator_signals if isinstance(curator_signals, list) else [],
            "sources": sources if isinstance(sources, list) else [],
            "source_warnings": [],
        },
    )


@app.get("/performance", response_class=HTMLResponse)
def performance_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "performance.html",
        {
            **_shell(request, "performance"),
            "total_trades": 0,
            "total_pnl": 0,
        },
    )


@app.get("/system", response_class=HTMLResponse)
def system_page(request: Request) -> HTMLResponse:
    client = _api(request)

    prod_res = client.get_producers_status()
    producers_map = prod_res.data.get("producers") if (prod_res.ok and isinstance(prod_res.data, dict)) else {}

    producers: list[dict[str, Any]] = []
    producers_healthy = 0
    if isinstance(producers_map, dict):
        for name, v in producers_map.items():
            if not isinstance(v, dict):
                continue
            healthy = v.get("healthy")
            health = "ok" if healthy is True else ("error" if healthy is False else "degraded")
            if healthy is True:
                producers_healthy += 1

            last_run = "—"
            if isinstance(v.get("last_run_at"), str):
                try:
                    dt = datetime.fromisoformat(str(v["last_run_at"]).replace("Z", "+00:00"))
                    last_run, _ = _age_str(dt)
                except Exception:
                    last_run = "—"

            producers.append({"name": str(name), "domain": v.get("domain") or "—", "health": health, "last_run": last_run})

    ks_res = client.get_kill_switch()
    ks_level = 0
    ks_changed = None
    if ks_res.ok and isinstance(ks_res.data, dict):
        try:
            ks_level = int(ks_res.data.get("kill_switch_level") or 0)
        except Exception:
            ks_level = 0
        ks_changed = ks_res.data.get("kill_switch_changed_at")

    kill_last_change = "never"
    if isinstance(ks_changed, str):
        try:
            dt = datetime.fromisoformat(ks_changed.replace("Z", "+00:00"))
            kill_last_change, _ = _age_str(dt)
        except Exception:
            pass

    label = "NORMAL" if ks_level == 0 else f"LEVEL {ks_level}"

    return templates.TemplateResponse(
        "system.html",
        {
            **_shell(request, "system", kill_switch_level=ks_level),
            "producers": producers,
            "producers_healthy": producers_healthy,
            "producers_total": len(producers),
            "kill_switch_level": ks_level,
            "kill_switch_label": label,
            "kill_switch_last_change": kill_last_change,
            "events_total": 0,
            "events_today": 0,
            "db_size": "—",
            "hash_chain_ok": True,
            "event_breakdown": [],
            "resources": [],
            "uptime": "—",
        },
    )


@app.get("/config", response_class=HTMLResponse)
def config_page(request: Request) -> HTMLResponse:
    client = _api(request)
    cfg_res = client._get_json("/config")

    cfg = cfg_res.data if (cfg_res.ok and isinstance(cfg_res.data, dict)) else {
        "risk": {},
        "brain": {},
        "execution": {},
        "karma": {},
    }
    return templates.TemplateResponse(
        "config.html",
        {
            **_shell(request, "config"),
            "preset": "custom",
            "presets": ["conservative", "balanced", "degen"],
            "cfg": cfg,
        },
    )


@app.get("/treasury", response_class=HTMLResponse)
def treasury_page(request: Request) -> HTMLResponse:
    client = _api(request)

    summary_res = client.get_karma_summary()
    intents_res = client.get_karma_intents()
    receipts_res = client.get_karma_receipts()

    intents = intents_res.data.get("items") if (intents_res.ok and isinstance(intents_res.data, dict)) else []
    receipts = receipts_res.data.get("items") if (receipts_res.ok and isinstance(receipts_res.data, dict)) else []

    pending_amount = "$0"
    lifetime_earned = "$0"
    settled_amount = "$0"
    receipts_count = len(receipts) if isinstance(receipts, list) else 0

    if summary_res.ok and isinstance(summary_res.data, dict):
        pending_n = summary_res.data.get("pending_intents")
        try:
            pending_n = int(pending_n)
        except Exception:
            pending_n = 0
        pending_amount = f"{pending_n} intents"

    karma_rate = "0.5% of profit"
    karma_mode = "manual"
    karma_threshold = "$50"
    treasury_addr = "—"
    if summary_res.ok and isinstance(summary_res.data, dict):
        pct = summary_res.data.get("percentage")
        if pct is not None:
            with contextlib.suppress(Exception):
                karma_rate = f"{float(pct) * 100:.2f}% of profit"
        treasury_addr = str(summary_res.data.get("treasury_address") or "—")

    return templates.TemplateResponse(
        "treasury.html",
        {
            **_shell(request, "treasury"),
            "intents": intents if isinstance(intents, list) else [],
            "receipts": receipts if isinstance(receipts, list) else [],
            "karma_rate": karma_rate,
            "karma_mode": karma_mode,
            "karma_threshold": karma_threshold,
            "treasury_addr": treasury_addr,
            "pending_amount": pending_amount,
            "lifetime_earned": lifetime_earned,
            "settled_amount": settled_amount,
            "receipts_count": receipts_count,
        },
    )


# ---- Partials ----------------------------------------------------------


@app.get("/partials/kill-dot", response_class=HTMLResponse)
def kill_dot(request: Request) -> HTMLResponse:
    client = _api(request)
    res = client.get_kill_switch()
    level = 0
    title = "Kill switch: stale"
    if res.ok and isinstance(res.data, dict):
        try:
            level = int(res.data.get("kill_switch_level") or 0)
            title = f"Kill switch: level {level}"
        except Exception:
            level = 0

    html = (
        f'<div class="kill-dot level-{level}" title="{title}" '
        'hx-get="/partials/kill-dot" hx-trigger="every 30s" hx-swap="outerHTML"></div>'
    )
    return HTMLResponse(html)


@app.get("/partials/regime-pill", response_class=HTMLResponse)
def regime_pill(request: Request) -> HTMLResponse:
    client = _api(request)
    res = client.get_regime()

    regime = "transition"
    label = "TRANSITION"
    if res.ok and isinstance(res.data, dict) and res.data.get("regime"):
        regime = str(res.data.get("regime"))
        label = str(res.data.get("regime")).upper()

    html = (
        f'<span class="regime-pill regime-{regime}" '
        'hx-get="/partials/regime-pill" hx-trigger="every 30s" hx-swap="outerHTML">'
        f"{label}</span>"
    )
    return HTMLResponse(html)


@app.get("/partials/regime-banner", response_class=HTMLResponse)
def regime_banner(request: Request) -> HTMLResponse:
    client = _api(request)
    res = client.get_regime()
    ctx = _regime_banner_context(res.data, stale=not res.ok)

    html = (
        f'<div class="regime-banner {ctx["regime_class"]}">'
        f'<span class="regime-name">{ctx["regime_name"]}</span>'
        f'<span class="regime-desc">{ctx["regime_desc"]}</span>'
        f'<span class="regime-confidence">{ctx["regime_confidence"]}</span>'
        "</div>"
    )
    return HTMLResponse(html)


@app.get("/partials/positions", response_class=HTMLResponse)
def positions_partial(request: Request) -> HTMLResponse:
    client = _api(request)
    res = client.get_positions()
    positions = _map_positions(res.data)

    return templates.TemplateResponse(
        "partials/positions_panel.html",
        {
            "request": request,
            "positions": positions,
            "positions_age": "—" if res.ok else "stale",
        },
    )


@app.get("/partials/position/{position_id}", response_class=HTMLResponse)
def position_partial(request: Request, position_id: str) -> HTMLResponse:
    client = _api(request)
    res = client.get_positions()
    positions = _map_positions(res.data)
    p = next((x for x in positions if x.get("id") == position_id), None)
    if p is None:
        return HTMLResponse('<div class="empty-state">Position not found.</div>')

    return templates.TemplateResponse(
        "partials/position_detail_panel.html",
        {"request": request, "p": p},
    )


@app.get("/partials/conviction", response_class=HTMLResponse)
def conviction_partial(request: Request) -> HTMLResponse:
    # API wiring for conviction is not implemented yet; keep graceful empty.
    return templates.TemplateResponse(
        "partials/conviction_panel.html",
        {
            "request": request,
            "convictions": [],
            "conviction_age": "stale",
            "domain_weights": [],
        },
    )


@app.get("/partials/signal-feed", response_class=HTMLResponse)
def signal_feed_partial(request: Request) -> HTMLResponse:
    client = _api(request)
    res = client.get_signals(domain=None)
    signals = _map_signals(res.data)
    total = res.data.get("total") if (res.ok and isinstance(res.data, dict)) else 0

    return templates.TemplateResponse(
        "partials/signal_feed.html",
        {"request": request, "signals": signals[:30], "total_signals": total},
    )


@app.get("/partials/system-status", response_class=HTMLResponse)
def system_status_partial(request: Request) -> HTMLResponse:
    client = _api(request)

    brain_res = client.get_kill_switch()
    cycle_age = "never"
    cycle_age_min = 10**9
    if brain_res.ok and isinstance(brain_res.data, dict):
        last_cycle_at = brain_res.data.get("last_cycle_at")
        if isinstance(last_cycle_at, str):
            try:
                dt = datetime.fromisoformat(last_cycle_at.replace("Z", "+00:00"))
                cycle_age, cycle_age_min = _age_str(dt)
            except Exception:
                pass

    prod_res = client.get_producers_status()
    producers = prod_res.data.get("producers") if (prod_res.ok and isinstance(prod_res.data, dict)) else {}
    producers_total = len(producers) if isinstance(producers, dict) else 0
    producers_healthy = 0
    if isinstance(producers, dict):
        for v in producers.values():
            if isinstance(v, dict) and v.get("healthy") is True:
                producers_healthy += 1

    treasury_res = client.get_karma_summary()
    karma_pending = "$0"
    if treasury_res.ok and isinstance(treasury_res.data, dict):
        pending_n = treasury_res.data.get("pending_intents")
        try:
            pending_n = int(pending_n)
        except Exception:
            pending_n = 0
        karma_pending = f"{pending_n} intents"

    return templates.TemplateResponse(
        "partials/system_status_panel.html",
        {
            "request": request,
            "cycle_age": cycle_age,
            "cycle_age_min": cycle_age_min,
            "producers_healthy": producers_healthy,
            "producers_total": producers_total,
            "events_today": 0,
            "db_size": "—",
            "uptime": "—",
            "karma_pending": karma_pending,
        },
    )


@app.get("/partials/producers", response_class=HTMLResponse)
def producers_partial(request: Request) -> HTMLResponse:
    client = _api(request)
    prod_res = client.get_producers_status()
    producers_map = prod_res.data.get("producers") if (prod_res.ok and isinstance(prod_res.data, dict)) else {}

    producers: list[dict[str, Any]] = []
    producers_healthy = 0
    if isinstance(producers_map, dict):
        for name, v in producers_map.items():
            if not isinstance(v, dict):
                continue
            healthy = v.get("healthy")
            health = "ok" if healthy is True else ("error" if healthy is False else "degraded")
            if healthy is True:
                producers_healthy += 1

            last_run = "—"
            if isinstance(v.get("last_run_at"), str):
                try:
                    dt = datetime.fromisoformat(str(v["last_run_at"]).replace("Z", "+00:00"))
                    last_run, _ = _age_str(dt)
                except Exception:
                    last_run = "—"

            producers.append({"name": str(name), "domain": v.get("domain") or "—", "health": health, "last_run": last_run})

    return templates.TemplateResponse(
        "partials/producers_panel.html",
        {
            "request": request,
            "producers": producers,
            "producers_healthy": producers_healthy,
            "producers_total": len(producers),
        },
    )


@app.get("/partials/kill-switch", response_class=HTMLResponse)
def kill_switch_partial(request: Request) -> HTMLResponse:
    client = _api(request)
    ks_res = client.get_kill_switch()

    level = 0
    changed_at = None
    if ks_res.ok and isinstance(ks_res.data, dict):
        try:
            level = int(ks_res.data.get("kill_switch_level") or 0)
        except Exception:
            level = 0
        changed_at = ks_res.data.get("kill_switch_changed_at")

    kill_last_change = "never"
    if isinstance(changed_at, str):
        try:
            dt = datetime.fromisoformat(changed_at.replace("Z", "+00:00"))
            kill_last_change, _ = _age_str(dt)
        except Exception:
            pass

    label = "NORMAL" if level == 0 else f"LEVEL {level}"

    return templates.TemplateResponse(
        "partials/kill_switch_panel.html",
        {
            "request": request,
            "kill_switch_level": level,
            "kill_switch_label": label,
            "kill_switch_last_change": kill_last_change,
        },
    )


@app.get("/partials/sentiment-map", response_class=HTMLResponse)
def sentiment_map_partial(request: Request) -> HTMLResponse:
    client = _api(request)
    res = client.get_social_sentiment()
    sentiments = res.data.get("items") if (res.ok and isinstance(res.data, dict)) else []

    return templates.TemplateResponse(
        "partials/sentiment_map_panel.html",
        {
            "request": request,
            "sentiment_age": "—" if res.ok else "stale",
            "sources_active": 0,
            "sentiments": sentiments if isinstance(sentiments, list) else [],
        },
    )


@app.get("/partials/social-alerts", response_class=HTMLResponse)
def social_alerts_partial(request: Request) -> HTMLResponse:
    client = _api(request)
    res = client.get_social_alerts()
    alerts = res.data.get("items") if (res.ok and isinstance(res.data, dict)) else []

    return templates.TemplateResponse(
        "partials/social_alerts_panel.html",
        {"request": request, "alerts": alerts if isinstance(alerts, list) else []},
    )


@app.get("/partials/curator-feed", response_class=HTMLResponse)
def curator_feed_partial(request: Request) -> HTMLResponse:
    client = _api(request)
    res = client.get_curator_feed()
    curator_signals = res.data.get("items") if (res.ok and isinstance(res.data, dict)) else []

    return templates.TemplateResponse(
        "partials/curator_feed.html",
        {"request": request, "curator_signals": curator_signals if isinstance(curator_signals, list) else []},
    )


@app.get("/partials/karma-intents", response_class=HTMLResponse)
def karma_intents_partial(request: Request) -> HTMLResponse:
    client = _api(request)
    res = client.get_karma_intents()
    intents = res.data.get("items") if (res.ok and isinstance(res.data, dict)) else []

    return templates.TemplateResponse(
        "partials/karma_intents_panel.html",
        {"request": request, "intents": intents if isinstance(intents, list) else []},
    )


@app.get("/partials/signal-history", response_class=HTMLResponse)
def signal_history_partial(request: Request, domain: str | None = None) -> HTMLResponse:
    client = _api(request)
    res = client.get_signals(domain=domain)
    signals = _map_signals(res.data)
    total = res.data.get("total") if (res.ok and isinstance(res.data, dict)) else 0

    return templates.TemplateResponse(
        "partials/signal_history.html",
        {"request": request, "signals": signals, "total_signals": total, "active_domain": domain},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=5051)
