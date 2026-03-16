"""b1e55ed dashboard — FastAPI + Jinja2 + HTMX.

Hashcash lineage precedes Bitcoin (1997). The code remembers.
"""

from __future__ import annotations

import contextlib
import json as _json
import logging
import os
import sqlite3
import time as _time
import urllib.request
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from dashboard.__version__ import VERSION as DASHBOARD_VERSION
from dashboard.services.api_client import ApiClient

_HERE = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)

# Cache for live price fallbacks: symbol -> (price, fetched_at_timestamp)
_price_cache: dict[str, tuple[float, float]] = {}
_PRICE_CACHE_TTL = 60.0  # seconds


@asynccontextmanager
async def _lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown lifecycle for the dashboard app."""
    from engine.core.config import Config
    from engine.core.paths import config_dir

    base_url = os.getenv("B1E55ED_API_BASE_URL", "http://127.0.0.1:5050/api/v1")
    token = os.getenv("B1E55ED_API_TOKEN")
    kill_switch_token = os.getenv("B1E55ED_KILL_SWITCH_TOKEN")
    if not token or not kill_switch_token:
        try:
            user_path = config_dir() / "user.yaml"
            cfg = Config.from_yaml(user_path) if user_path.exists() else Config.from_repo_defaults(None)
            if not token:
                token = str(getattr(cfg.api, "auth_token", "") or "")
            if not kill_switch_token:
                kill_switch_token = str(getattr(cfg.api, "kill_switch_token", "") or "")
        except Exception:
            pass

    application.state.api_client = ApiClient(base_url=base_url, token=token or None)
    application.state.kill_switch_api_client = ApiClient(base_url=base_url, token=kill_switch_token or token or None)
    yield


app = FastAPI(title="b1e55ed dashboard", docs_url=None, redoc_url=None, lifespan=_lifespan)
app.mount("/static", StaticFiles(directory=_HERE / "static"), name="static")

templates = Jinja2Templates(directory=_HERE / "templates")


# ---- Jinja2 custom filters ------------------------------------------------


def _parse_dt(value: Any) -> datetime | None:
    """Parse ISO-8601, Unix timestamp (sec/ms), or datetime to UTC-aware datetime."""
    if value is None or value == "":
        return None

    dt: datetime | None = None

    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if not s:
            return None

        # Numeric values may be epoch seconds or epoch milliseconds.
        with contextlib.suppress(ValueError, OSError):
            epoch = float(s)
            if abs(epoch) > 1e12:
                epoch /= 1000.0
            if abs(epoch) > 1e8:  # ignore tiny numerics that are clearly not timestamps
                dt = datetime.fromtimestamp(epoch, tz=UTC)

        if dt is None:
            normalized = s.replace(" ", "T") if " " in s and "T" not in s else s
            if normalized.endswith("Z"):
                normalized = normalized[:-1] + "+00:00"
            with contextlib.suppress(ValueError, TypeError):
                dt = datetime.fromisoformat(normalized)

    if dt is None:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _timeago_filter(value: Any) -> str:
    """Convert ISO-8601, Unix timestamp, or datetime to relative string."""
    if value is None or value == "" or value == "—":
        return "—"

    dt = _parse_dt(value)
    if dt is None:
        return str(value)

    now = datetime.now(tz=UTC)
    delta = now - dt
    secs = int(delta.total_seconds())

    if secs < 60:
        return "just now"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m ago"
    hrs = mins // 60
    if hrs < 24:
        return f"{hrs}h ago"
    days = hrs // 24
    if days < 30:
        return f"{days}d ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    return f"{days // 365}y ago"


def _fmt_iso_filter(value: Any) -> str:
    """Return full ISO string for tooltip display."""
    if value is None or value == "" or value == "—":
        return ""
    dt = _parse_dt(value)
    if dt is None:
        return str(value)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


templates.env.filters["timeago"] = _timeago_filter
templates.env.filters["fmt_iso"] = _fmt_iso_filter


# ---- Market ticker cache ---------------------------------------------------

_ticker_cache: dict[str, Any] = {"data": None, "fetched_at": 0.0}
templates.env.globals["dashboard_version"] = DASHBOARD_VERSION


def _repo_root() -> Path:
    override = os.environ.get("B1E55ED_REPO_ROOT")
    if override:
        return Path(override)
    from engine.core.paths import b1e55ed_dir

    return b1e55ed_dir()


@app.middleware("http")
async def _identity_gate(request: Request, call_next):
    # Always allow static assets
    if request.url.path.startswith("/static"):
        return await call_next(request)

    # Dev/test bypass
    if os.environ.get("B1E55ED_DEV_MODE", "").lower() in ("1", "true", "yes"):
        return await call_next(request)

    from engine.core.identity_gate import load_identity

    identity = load_identity(_repo_root())
    if identity is None:
        return templates.TemplateResponse(
            request=request,
            name="forge_required.html",
            context={
                "request": request,
                "active_page": "identity",
                "kill_switch_level": 0,
                "regime": "transition",
            },
            status_code=403,
        )

    return await call_next(request)


def _api(request: Request) -> ApiClient:
    return request.app.state.api_client


def _kill_switch_api(request: Request) -> ApiClient:
    client = getattr(request.app.state, "kill_switch_api_client", None)
    return client if isinstance(client, ApiClient) else _api(request)


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


def _get_sentiment_horizons() -> list[dict[str, Any]]:
    """Query brain.db for recent social signal scores grouped by producer (last 24 data points)."""
    try:
        db_path = _get_brain_db()

        if not db_path:
            return []

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # Check if signal_log table exists
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if "signal_log" not in tables:
            conn.close()
            return []

        # Get columns to check for domain/producer_id fields
        cols = [str(r[1]) for r in conn.execute("PRAGMA table_info(signal_log)").fetchall()]

        producer_col = "producer_id" if "producer_id" in cols else ("source" if "source" in cols else None)
        score_col = "score" if "score" in cols else ("confidence" if "confidence" in cols else None)

        if not producer_col or not score_col:
            conn.close()
            return []

        # Filter to social-domain signals if domain column exists
        domain_filter = ""
        if "domain" in cols:
            domain_filter = " AND domain IN ('social', 'sentiment') "

        # Query: last 24 data points per producer, ordered by time
        query = f"""
            SELECT {producer_col} AS producer, {score_col} AS score, created_at
            FROM signal_log
            WHERE {score_col} IS NOT NULL {domain_filter}
            ORDER BY created_at DESC
            LIMIT 500
        """
        rows = conn.execute(query).fetchall()
        conn.close()

        if not rows:
            return []

        # Group by producer, keep last 24 per producer
        by_producer: dict[str, list[float]] = {}
        for r in rows:
            p = str(r["producer"])
            if p not in by_producer:
                by_producer[p] = []
            if len(by_producer[p]) < 24:
                by_producer[p].append(float(r["score"]))

        # Reverse so oldest first
        horizons = []
        for name, scores in by_producer.items():
            scores.reverse()
            # Normalize scores to 0-1 range if they're on 0-10 scale
            normalized = [s / 10.0 if s > 1.0 else s for s in scores]
            horizons.append({"name": name, "scores": normalized})

        return horizons

    except Exception:
        return []


def _shell(request: Request, active_page: str, *, kill_switch_level: int = 0, regime: str | None = None) -> dict[str, Any]:
    return {
        "request": request,
        "active_page": active_page,
        "kill_switch_level": kill_switch_level,
        "regime": regime or "transition",
    }


def _fetch_live_price_fallback(sym: str) -> float:
    """Fetch live price for *sym* from Binance (then CoinGecko) with a 60-s cache.

    Returns 0.0 if all sources fail so callers can distinguish missing from valid zero.
    """
    now = _time.monotonic()
    cached = _price_cache.get(sym)
    if cached is not None:
        price, ts = cached
        if now - ts < _PRICE_CACHE_TTL:
            return price

    price = 0.0
    source = "none"

    # --- Binance ---
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={sym}USDT"
        with urllib.request.urlopen(url, timeout=3) as resp:  # noqa: S310
            data = _json.loads(resp.read())
        price = float(data["price"])
        source = "binance"
    except Exception:
        pass

    # --- CoinGecko fallback ---
    if price == 0.0:
        try:
            cg_id = sym.lower()
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd"
            with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310
                data = _json.loads(resp.read())
            price = float(data[cg_id]["usd"])
            source = "coingecko"
        except Exception:
            pass

    if price != 0.0:
        logger.warning("price_ws_miss_fallback symbol=%s source=%s price=%s", sym, source, price)
        _price_cache[sym] = (price, now)

    return price


def _latest_mark_prices(symbols: set[str] | None = None) -> dict[str, float]:
    """Best-effort latest mark prices from WS price signals."""
    requested = {str(s).strip().upper() for s in (symbols or set()) if str(s).strip()}

    db_path = _get_brain_db()
    if db_path is None:
        return {}

    prices: dict[str, float] = {}
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(str(db_path))
        if requested:
            for sym in requested:
                row = conn.execute(
                    """
                    SELECT json_extract(payload, '$.price')
                    FROM events
                    WHERE type = 'signal.price_ws.v1'
                      AND json_extract(payload, '$.symbol') = ?
                    ORDER BY ts DESC
                    LIMIT 1
                    """,
                    (sym,),
                ).fetchone()
                if row and row[0] is not None:
                    with contextlib.suppress(Exception):
                        prices[sym] = float(row[0])
            # Fetch live price for any symbol missing from DB
            missing = requested - prices.keys()
            for sym in missing:
                prices[sym] = _fetch_live_price_fallback(sym)
            return prices

        rows = conn.execute(
            """
            SELECT json_extract(payload, '$.symbol') AS symbol,
                   json_extract(payload, '$.price') AS price
            FROM events
            WHERE type = 'signal.price_ws.v1'
            ORDER BY ts DESC
            LIMIT 500
            """
        ).fetchall()
    except Exception:
        return {}
    finally:
        if conn is not None:
            conn.close()

    for symbol, price in rows:
        sym = str(symbol or "").strip().upper()
        if not sym or sym in prices or price is None:
            continue
        with contextlib.suppress(Exception):
            prices[sym] = float(price)
    return prices


def _map_positions(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []

    symbols = {
        str(p.get("asset") or p.get("symbol") or "").strip().upper()
        for p in raw
        if isinstance(p, dict) and str(p.get("asset") or p.get("symbol") or "").strip()
    }
    mark_prices = _latest_mark_prices(symbols=symbols)

    out: list[dict[str, Any]] = []
    for p in raw:
        if not isinstance(p, dict):
            continue

        entry = float(p.get("entry_price") or 0.0)
        stop = float(p.get("stop_loss") or entry)
        target = float(p.get("take_profit") or entry)
        leverage = float(p.get("leverage") or 1.0)
        direction = str(p.get("direction") or "neutral").lower()
        asset = str(p.get("asset") or p.get("symbol") or "—").upper()
        symbol = asset
        status = str(p.get("status") or "")
        size_notional = float(p.get("size_notional") or 0.0)
        notional_for_pnl = abs(size_notional)
        if notional_for_pnl <= 0:
            # Fallback for APIs that expose quantity but not notional.
            with contextlib.suppress(Exception):
                qty = abs(float(p.get("size") or p.get("qty") or p.get("quantity") or 0.0))
                if qty > 0 and entry > 0:
                    notional_for_pnl = qty * entry

        # Display-level guard for legacy rows with inverted short risk levels.
        risk_levels_autocorrected = False
        if direction in {"short", "sell"} and entry > 0 and stop < entry:
            stop, target = target, stop
            risk_levels_autocorrected = True
        elif direction in {"long", "buy"} and entry > 0 and stop > entry and target < entry:
            stop, target = target, stop

        current_price = mark_prices.get(asset) if asset and asset != "—" else None
        if current_price is None:
            current = float(entry if entry > 0 else 0.0)
        else:
            current = float(current_price)

        if status.lower() == "closed":
            pnl_usd = float(p.get("realized_pnl") or 0.0)
            # Compute pct from realized_pnl / notional (positions table has no pnl_pct col)
            _notional = abs(float(p.get("size_notional") or 0.0))
            pnl_pct = (pnl_usd / _notional * 100.0) if _notional > 0 else 0.0
        else:
            if direction in {"short", "sell"}:
                pnl_pct = ((entry - current) / entry * 100.0) if entry > 0 else 0.0
            else:
                pnl_pct = ((current - entry) / entry * 100.0) if entry > 0 else 0.0
            pnl_usd = (pnl_pct / 100.0) * notional_for_pnl if notional_for_pnl > 0 else 0.0

        near_stop = False
        if entry > 0 and stop > 0 and current > 0:
            if direction in {"short", "sell"}:
                near_stop = current >= stop * 0.995
            else:
                near_stop = current <= stop * 1.005

        out.append(
            {
                "id": str(p.get("id") or "—"),
                "symbol": symbol,
                "direction": direction,
                "current": current,
                "current_price": current_price,
                "entry": entry,
                "stop": stop,
                "target": target,
                "risk_levels_autocorrected": risk_levels_autocorrected,
                "pnl_pct": pnl_pct,
                "pnl_usd": pnl_usd,
                "leverage": leverage,
                "leverage_warning": False,
                "near_stop": near_stop,
                "opened": p.get("opened_at"),
                "conviction_entry": p.get("conviction_id"),
                "conviction_current": "—",
                "conviction_conflict": False,
                "regime_entry": p.get("regime_at_entry"),
                "held": None,
                "status": p.get("status"),
            }
        )
    return out


def _normalize_trade_direction(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"long", "buy", "bull", "bullish", "up", "▲", "+", "1"}:
        return "long"
    if raw in {"short", "sell", "bear", "bearish", "down", "▼", "-", "-1"}:
        return "short"
    return "neutral"


def _direction_label(direction: str) -> str:
    if direction == "long":
        return "bullish"
    if direction == "short":
        return "bearish"
    return "neutral"


def _latest_convictions_by_symbol(client: Any, symbols: set[str] | None = None) -> dict[str, dict[str, Any]]:
    requested = {str(s).strip().upper() for s in (symbols or set()) if str(s).strip()}

    rows: list[dict[str, Any]] = []
    get_convictions = getattr(client, "get_convictions", None)
    if callable(get_convictions):
        with contextlib.suppress(Exception):
            limit = max(20, len(requested) * 4) if requested else 50
            res = get_convictions(limit=limit)
            payload = res.data if getattr(res, "ok", False) else None
            if isinstance(payload, list):
                rows = [r for r in payload if isinstance(r, dict)]
            elif isinstance(payload, dict):
                raw_items = payload.get("items")
                if isinstance(raw_items, list):
                    rows = [r for r in raw_items if isinstance(r, dict)]

    if not rows:
        db_path = _get_brain_db()
        if db_path:
            try:
                conn = sqlite3.connect(str(db_path))
                conn.row_factory = sqlite3.Row
                raw = conn.execute(
                    """
                    SELECT cs.symbol, cs.direction, cs.confidence, cs.ts
                    FROM conviction_scores cs
                    INNER JOIN (
                        SELECT symbol, MAX(ts) AS max_ts
                        FROM conviction_scores
                        GROUP BY symbol
                    ) latest ON cs.symbol = latest.symbol AND cs.ts = latest.max_ts
                    ORDER BY cs.ts DESC
                    """
                ).fetchall()
                conn.close()
                rows = [dict(r) for r in raw]
            except Exception:
                rows = []

    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        sym = str(row.get("symbol") or "").strip().upper()
        if not sym:
            continue
        if requested and sym not in requested:
            continue

        raw_direction = str(row.get("direction") or "neutral").strip().lower()
        normalized = _normalize_trade_direction(raw_direction)

        ts = _parse_dt(row.get("ts"))
        ts_key = ts.timestamp() if ts is not None else float("-inf")

        prev = out.get(sym)
        if prev is not None and ts_key <= float(prev.get("_ts_key", float("-inf"))):
            continue

        confidence = None
        with contextlib.suppress(Exception):
            confidence = float(row.get("confidence")) if row.get("confidence") is not None else None

        out[sym] = {
            "symbol": sym,
            "normalized_direction": normalized,
            "label": _direction_label(normalized),
            "confidence": confidence,
            "_ts_key": ts_key,
        }

    for data in out.values():
        data.pop("_ts_key", None)

    return out


def _annotate_positions_with_convictions(positions: list[dict[str, Any]], client: Any) -> list[dict[str, Any]]:
    if not positions:
        return positions

    symbols = {str(p.get("symbol") or "").strip().upper() for p in positions if str(p.get("symbol") or "").strip()}
    conviction_map = _latest_convictions_by_symbol(client, symbols=symbols)

    for p in positions:
        symbol = str(p.get("symbol") or "").strip().upper()
        pos_direction = _normalize_trade_direction(p.get("direction"))

        conviction = conviction_map.get(symbol)
        if conviction is None:
            p["conviction_current"] = p.get("conviction_current") or "—"
            p["conviction_conflict"] = False
            continue

        conviction_direction = str(conviction.get("normalized_direction") or "neutral")
        p["conviction_current"] = str(conviction.get("label") or "—")
        p["conviction_conflict"] = pos_direction in {"long", "short"} and conviction_direction in {"long", "short"} and pos_direction != conviction_direction

    return positions


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
        payload: dict[str, Any] = s.get("payload") if isinstance(s.get("payload"), dict) else {}
        t = str(s.get("type") or "")
        domain = _domain_from_type(t)

        ts = s.get("ts")
        ts_dt = _parse_dt(ts)
        ts_hm = ts_dt.strftime("%H:%M") if ts_dt is not None else "—"
        ts_iso = ts_dt.isoformat() if ts_dt is not None else (str(ts) if ts is not None else "")
        ts_ms = int(ts_dt.timestamp() * 1000) if ts_dt is not None else None

        asset = payload.get("asset") or payload.get("symbol") or payload.get("token") or "—"
        symbol = str(asset).upper().strip() if asset else "—"
        venue = payload.get("venue") or payload.get("exchange") or payload.get("market") or ""
        desc = payload.get("desc") or payload.get("description") or payload.get("message") or t

        # Derive score and direction from domain-specific payloads.
        # Producers emit raw domain data; payload.score/direction are often unset.
        # This is display-only — the Brain uses its own feature extraction.
        score_f = 0.0
        direction = "→"

        # Check if producer already set score/direction (e.g. social)
        _raw_score = payload.get("score")
        _raw_dir = payload.get("direction")

        if _raw_score is not None and _raw_dir in {"▲", "▼", "→"}:
            # Producer set both — trust them
            try:
                score_f = float(_raw_score)
            except (ValueError, TypeError):
                score_f = 0.0
            direction = _raw_dir
        else:
            # Derive from domain-specific fields
            try:
                if domain in ("technical", "ta"):
                    # TA signals: use RSI to derive score
                    rsi = payload.get("rsi_14") or payload.get("rsi")
                    if rsi is not None:
                        rsi = float(rsi)
                        if rsi < 30:
                            # Oversold = bullish signal
                            score_f = min(10.0, (30 - rsi) / 3.0)  # 0-10 scale
                            direction = "▲"
                        elif rsi > 70:
                            # Overbought = bearish signal
                            score_f = min(10.0, (rsi - 70) / 3.0)
                            direction = "▼"
                        else:
                            score_f = 5.0 * abs(rsi - 50) / 20.0
                            direction = "→"
                elif domain == "orderbook":
                    # Orderbook signals: use imbalance
                    imbalance = payload.get("imbalance")
                    if imbalance is not None:
                        imbalance = float(imbalance)
                        score_f = min(10.0, abs(imbalance) * 10.0)
                        if imbalance > 0.1:
                            direction = "▲"
                        elif imbalance < -0.1:
                            direction = "▼"
                        else:
                            direction = "→"
                elif domain == "whale" or domain == "onchain":
                    # Whale/onchain signals: use smart_money_netflow
                    netflow = payload.get("smart_money_netflow") or payload.get("netflow")
                    if netflow is not None:
                        netflow = float(netflow)
                        score_f = min(10.0, abs(netflow) * 5.0)
                        direction = "▲" if netflow > 0 else ("▼" if netflow < 0 else "→")
                elif domain == "tradfi":
                    # TradFi signals: use meltup_score if present, else basis
                    meltup = payload.get("meltup_score")
                    if meltup is not None:
                        score_f = min(10.0, max(0.0, float(meltup)))
                        direction = "▲" if score_f > 5 else ("▼" if score_f < 3 else "→")
                    else:
                        basis = payload.get("basis") or payload.get("basis_pct")
                        if basis is not None:
                            basis = float(basis)
                            score_f = min(10.0, abs(basis) * 2.0)
                            direction = "▲" if basis > 0 else "▼"
                elif domain == "social":
                    # Social signals: payload.score usually set by producer
                    if _raw_score is not None:
                        score_f = max(0.0, min(10.0, float(_raw_score)))
                        direction = _raw_dir if _raw_dir in {"▲", "▼", "→"} else "→"
                elif domain == "stablecoin":
                    # Stablecoin signals: use supply_change_24h
                    supply_chg = payload.get("supply_change_24h") or payload.get("supply_change")
                    if supply_chg is not None:
                        supply_chg = float(supply_chg)
                        score_f = min(10.0, abs(supply_chg) / 1e8)  # normalize
                        direction = "▲" if supply_chg > 0 else ("▼" if supply_chg < 0 else "→")
            except (ValueError, TypeError):
                score_f = 0.0
                direction = "→"

            # Fallback: if we still have no score, try raw payload.score
            if score_f == 0.0 and _raw_score is not None:
                with contextlib.suppress(Exception):
                    score_f = float(_raw_score)
            if direction == "→" and _raw_dir in {"▲", "▼"}:
                direction = _raw_dir

        out.append(
            {
                # Keep both normalized timestamp and epoch-ms for reliable timeline plotting.
                "ts": str(ts) if ts is not None else "",
                "ts_iso": ts_iso,
                "ts_ms": ts_ms,
                "ts_hm": ts_hm,
                "domain": domain,
                "asset": str(asset),
                "symbol": symbol,
                "venue": str(venue),
                "desc": str(desc),
                "direction": str(direction),
                "score": score_f,
            }
        )

    return out


def _normalize_symbols(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        sym = str(raw or "").strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    return out


def _normalize_tags(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        tag = str(raw or "").strip().lower()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out


def _universe_bundle_context(client: Any) -> dict[str, Any]:
    packs: list[dict[str, Any]] = []
    get_packs = getattr(client, "get_universe_packs", None)
    if callable(get_packs):
        packs_res = get_packs()
        packs_data = packs_res.data if (packs_res.ok and isinstance(packs_res.data, dict)) else {}
        packs_raw = packs_data.get("items") if isinstance(packs_data, dict) else []
        packs = [p for p in packs_raw if isinstance(p, dict)] if isinstance(packs_raw, list) else []

    pack_map = {str(p.get("id") or ""): p for p in packs if str(p.get("id") or "")}

    bundles_res = client.get_universe_bundles()
    bundles_data = bundles_res.data if (bundles_res.ok and isinstance(bundles_res.data, dict)) else {}
    bundles_raw = bundles_data.get("items") if isinstance(bundles_data, dict) else []
    bundles = [b for b in bundles_raw if isinstance(b, dict)] if isinstance(bundles_raw, list) else []

    active_res = client.get_universe_active()
    active_data = active_res.data if (active_res.ok and isinstance(active_res.data, dict)) else {}
    active_symbols = _normalize_symbols(active_data.get("symbols") if isinstance(active_data, dict) else [])

    enabled_bundle_ids = set(active_data.get("enabled_bundle_ids") or []) if isinstance(active_data, dict) else set()
    if not enabled_bundle_ids:
        enabled_bundle_ids = {str(b.get("id")) for b in bundles if bool(b.get("enabled", True)) and b.get("id")}

    bundle_symbol_map: dict[str, list[str]] = {}
    for b in bundles:
        bid = str(b.get("id") or "").strip()
        if not bid:
            continue
        syms = _normalize_symbols(b.get("symbols") if isinstance(b.get("symbols"), list) else [])
        bundle_symbol_map[bid] = syms

    asset_class_symbol_map: dict[str, list[str]] = {}
    raw_asset_map = active_data.get("asset_class_symbols") if isinstance(active_data, dict) else {}
    if isinstance(raw_asset_map, dict) and raw_asset_map:
        for k, v in raw_asset_map.items():
            asset_class_symbol_map[str(k)] = _normalize_symbols(v if isinstance(v, list) else [])
    else:
        agg: dict[str, list[str]] = {}
        for b in bundles:
            if str(b.get("id") or "") not in enabled_bundle_ids:
                continue
            acls = str(b.get("asset_class") or "").strip()
            if not acls:
                continue
            agg.setdefault(acls, []).extend(bundle_symbol_map.get(str(b.get("id")), []))
        asset_class_symbol_map = {k: _normalize_symbols(v) for k, v in agg.items()}

    venue_symbol_map: dict[str, list[str]] = {}
    raw_venue_map = active_data.get("venue_symbols") if isinstance(active_data, dict) else {}
    if isinstance(raw_venue_map, dict) and raw_venue_map:
        for k, v in raw_venue_map.items():
            venue_symbol_map[str(k)] = _normalize_symbols(v if isinstance(v, list) else [])
    else:
        agg_v: dict[str, list[str]] = {}
        for b in bundles:
            if str(b.get("id") or "") not in enabled_bundle_ids:
                continue
            venue = str(b.get("venue") or "").strip()
            if not venue:
                continue
            agg_v.setdefault(venue, []).extend(bundle_symbol_map.get(str(b.get("id")), []))
        venue_symbol_map = {k: _normalize_symbols(v) for k, v in agg_v.items()}

    tag_symbol_map: dict[str, list[str]] = {}
    raw_tag_map = active_data.get("tag_symbols") if isinstance(active_data, dict) else {}
    if isinstance(raw_tag_map, dict) and raw_tag_map:
        for k, v in raw_tag_map.items():
            tag_symbol_map[str(k)] = _normalize_symbols(v if isinstance(v, list) else [])
    else:
        agg_t: dict[str, list[str]] = {}
        for b in bundles:
            if str(b.get("id") or "") not in enabled_bundle_ids:
                continue
            tags = _normalize_tags(b.get("tags") if isinstance(b.get("tags"), list) else [])
            symbols = bundle_symbol_map.get(str(b.get("id")), [])
            for tag in tags:
                agg_t.setdefault(tag, []).extend(symbols)
        tag_symbol_map = {k: _normalize_symbols(v) for k, v in agg_t.items()}

    asset_classes = sorted(asset_class_symbol_map.keys())
    venues = sorted(venue_symbol_map.keys())
    tags = sorted(tag_symbol_map.keys())

    return {
        "packs": packs,
        "pack_map": pack_map,
        "bundles": bundles,
        "active_symbols": active_symbols,
        "enabled_bundle_ids": sorted(enabled_bundle_ids),
        "bundle_symbol_map": bundle_symbol_map,
        "asset_class_symbol_map": asset_class_symbol_map,
        "venue_symbol_map": venue_symbol_map,
        "tag_symbol_map": tag_symbol_map,
        "asset_classes": asset_classes,
        "venues": venues,
        "tags": tags,
        "fallback_to_symbols": bool(active_data.get("fallback_to_symbols", True)) if isinstance(active_data, dict) else True,
    }


def _build_conviction_ctx(client: Any) -> dict[str, Any]:
    """Fetch conviction scores — tries API first, falls back to direct DB read."""
    raw: list[dict] = []
    res = client.get_convictions(limit=20)
    if res.ok and isinstance(res.data, list) and res.data:
        raw = res.data
    else:
        # Fallback: read directly from DB (handles older API versions without the endpoint)
        try:
            db_path = _get_brain_db()
            if db_path is not None:
                import sqlite3

                conn = sqlite3.connect(str(db_path))
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT cs.* FROM conviction_scores cs
                    INNER JOIN (
                        SELECT symbol, MAX(ts) as max_ts FROM conviction_scores GROUP BY symbol
                    ) latest ON cs.symbol = latest.symbol AND cs.ts = latest.max_ts
                    ORDER BY cs.confidence DESC LIMIT 20
                    """
                ).fetchall()
                raw = [dict(r) for r in rows]
                conn.close()
        except Exception:
            pass
    if not raw:
        return {"convictions": [], "conviction_age": "—"}
    convictions = []
    for c in raw:
        ts_str = c.get("ts")
        age = "—"
        if ts_str:
            try:
                dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
                age, _ = _age_str(dt)
            except Exception:
                pass
        convictions.append(
            {
                "symbol": c.get("symbol", "?"),
                "direction": c.get("direction", "neutral"),
                "confidence": round(float(c.get("confidence") or 0), 1),
                "magnitude": round(float(c.get("magnitude") or 0), 1),
                "timeframe": c.get("timeframe", "—"),
                "regime": c.get("regime", "—"),
                "pcs_score": c.get("pcs_score"),
                "cts_score": c.get("cts_score"),
                "age": age,
            }
        )
    # Overall age = age of most-recent score
    first_age = convictions[0]["age"] if convictions else "—"
    return {"convictions": convictions, "conviction_age": first_age}


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


# ---- Market ticker -------------------------------------------------------


@app.get("/api/market-ticker")
def market_ticker() -> JSONResponse:
    """BTC/ETH/SOL prices with 24h change. Cached 60s."""
    import json as _json
    import urllib.request

    now = _time.time()
    if _ticker_cache["data"] is not None and (now - _ticker_cache["fetched_at"]) < 60:
        return JSONResponse(_ticker_cache["data"])

    url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana&vs_currencies=usd&include_24hr_change=true"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "b1e55ed-dashboard/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = _json.loads(resp.read())
    except Exception:
        if _ticker_cache["data"] is not None:
            return JSONResponse(_ticker_cache["data"])
        return JSONResponse({"coins": []})

    coins = []
    for cg_id, symbol in [("bitcoin", "BTC"), ("ethereum", "ETH"), ("solana", "SOL")]:
        info = raw.get(cg_id, {})
        price = info.get("usd", 0)
        change = info.get("usd_24h_change", 0)
        coins.append({"symbol": symbol, "price": price, "change_24h": round(change, 2) if change else 0})

    result = {"coins": coins}
    _ticker_cache["data"] = result
    _ticker_cache["fetched_at"] = now
    return JSONResponse(result)


# ---- Page routes -------------------------------------------------------


# The dashboard doesn't know the system. It asks the system to know itself.
# Descartes ran the other direction: cogito ergo sum — I think, therefore I am.
# We measure, therefore we exist.
def _system_status_ctx() -> dict[str, Any]:
    """Returns db_size, uptime, and events_today for System Status panel."""
    db_size: str = "—"
    events_today: int = 0
    uptime: str = "—"
    try:
        db_path = _get_brain_db()
        if db_path is not None:
            size_bytes = db_path.stat().st_size
            if size_bytes >= 1_048_576:
                db_size = f"{size_bytes / 1_048_576:.1f} MB"
            else:
                db_size = f"{size_bytes / 1024:.0f} KB"
            conn = sqlite3.connect(str(db_path))
            row = conn.execute("SELECT COUNT(*) FROM events WHERE ts >= date('now')").fetchone()
            events_today = int(row[0]) if row else 0
            conn.close()
    except Exception:
        pass
    try:
        import time

        pid_file = Path("/tmp/b1e55ed_start_time")
        if pid_file.exists():
            start = float(pid_file.read_text().strip())
            secs = int(time.time() - start)
            if secs >= 3600:
                uptime = f"{secs // 3600}h {(secs % 3600) // 60}m"
            else:
                uptime = f"{secs // 60}m"
        else:
            # Estimate from process start time via /proc
            import resource

            _ = resource.getrusage(resource.RUSAGE_SELF)
            proc_stat = Path(f"/proc/{os.getpid()}/stat")
            if proc_stat.exists():
                fields = proc_stat.read_text().split()
                hz = os.sysconf("SC_CLK_TCK")
                start_ticks = int(fields[21])
                btime = int(next(line.split()[1] for line in Path("/proc/stat").read_text().splitlines() if line.startswith("btime")))
                start_epoch = btime + start_ticks / hz
                secs = int(time.time() - start_epoch)
                if secs >= 3600:
                    uptime = f"{secs // 3600}h {(secs % 3600) // 60}m"
                else:
                    uptime = f"{secs // 60}m"
    except Exception:
        pass
    return {"db_size": db_size, "events_today": events_today, "uptime": uptime}


def _is_new_operator() -> bool:
    """Returns True if no signals have been processed yet."""
    try:
        db_path = _get_brain_db()
        if not db_path or not db_path.exists():
            return True
        conn = sqlite3.connect(str(db_path))
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if "conviction_scores" not in tables:
            conn.close()
            return True
        count = conn.execute("SELECT COUNT(*) FROM conviction_scores").fetchone()[0]
        conn.close()
        return count == 0
    except Exception:
        return False


@app.get("/home", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    # kept for backward-compat with early shell
    return templates.TemplateResponse(request=request, name="home.html", context={**_shell(request, "brain")})


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
    _all_pos = _annotate_positions_with_convictions(_map_positions(pos_res.data), client)
    positions = [p for p in _all_pos if str(p.get("status") or "").lower() != "closed"]
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

    # Fetch cockpit state for merged brain+cockpit page
    cockpit_state: dict[str, Any] = {}
    try:
        cockpit_res = client.get_cockpit_state()
        if cockpit_res.ok and isinstance(cockpit_res.data, dict):
            cockpit_state = cockpit_res.data
    except Exception:
        pass

    return templates.TemplateResponse(
        request=request,
        name="brain.html",
        context={
            **_shell(request, "brain", kill_switch_level=ks_level, regime=regime_ctx.get("regime_class")),
            **regime_ctx,
            "positions": positions,
            "positions_age": positions_age,
            **_build_conviction_ctx(client),
            "domain_weights": [],
            "signals": signals[:12],
            "total_signals": total_signals or 0,
            "cycle_age": cycle_age,
            "cycle_age_min": cycle_age_min,
            "producers_healthy": producers_healthy,
            "producers_total": producers_total,
            **_system_status_ctx(),
            "karma_pending": karma_pending,
            "disc_signals": _query_discretionary_signals(),
            "regime_history": _query_regime_history_for_brain(),
            "is_new_operator": _is_new_operator(),
            "cockpit_state": cockpit_state,
            "conviction_value": cockpit_state.get("conviction"),
        },
    )


@app.get("/positions", response_class=HTMLResponse)
def positions_page(request: Request, view: str = "open") -> HTMLResponse:
    client = _api(request)
    res = client.get_positions()
    all_positions = _annotate_positions_with_convictions(_map_positions(res.data), client)

    if view == "closed":
        positions = [p for p in all_positions if str(p.get("status") or "").lower() == "closed"]
    else:
        positions = [p for p in all_positions if str(p.get("status") or "").lower() != "closed"]

    return templates.TemplateResponse(
        request=request,
        name="positions.html",
        context={
            **_shell(request, "positions"),
            "view": view,
            "positions": positions,
        },
    )


def _get_brain_db() -> Path | None:
    """Resolve path to brain.db — shared helper used by all DB-querying functions.

    Delegates to get_db_path() for the canonical path, then honours the legacy
    B1E55ED_DB_PATH env var as a direct full-path override (dashboard-only escape
    hatch, primarily used in tests).
    """
    try:
        from engine.core.paths import get_db_path

        db_path = get_db_path()
    except Exception:
        # engine.core.paths unavailable — cannot resolve DB path.
        return None

    # Legacy full-path override (tests, custom deployments).
    db_override = os.getenv("B1E55ED_DB_PATH")
    if db_override:
        db_path = Path(db_override)

    return db_path if db_path.exists() else None


def _query_regime_history_for_brain() -> list[dict[str, Any]]:
    """Regime history for brain home page."""
    db_path = _get_brain_db()
    if not db_path:
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    results: list[dict[str, Any]] = []
    if "events" in tables:
        raw = conn.execute("SELECT payload, ts FROM events WHERE type LIKE '%regime%' OR type LIKE '%REGIME%' ORDER BY ts DESC LIMIT 20").fetchall()
        if raw:
            import json as _json  # noqa: PLC0415

            for r in raw:
                d = dict(r)
                # Try to parse payload for regime name
                regime = "unknown"
                with contextlib.suppress(Exception):
                    p = _json.loads(d.get("payload", "{}"))
                    regime = p.get("regime") or p.get("new_regime") or p.get("name") or "unknown"
                results.append({"regime": regime, "ts": d.get("ts", ""), "first_seen": None, "last_seen": None, "cycles": None})
            conn.close()
            return results
    if "conviction_scores" in tables:
        raw = conn.execute(
            "SELECT regime, MIN(ts) as first_seen, MAX(ts) as last_seen, COUNT(*) as cycles FROM conviction_scores GROUP BY regime ORDER BY last_seen DESC"
        ).fetchall()
        results = [dict(r) for r in raw]
    conn.close()
    return results


def _query_forecasts(asset: str | None = None, horizon: str | None = None, status: str = "pending") -> dict[str, Any]:
    """Query forecast_calibration from brain.db."""
    db_path = _get_brain_db()
    if not db_path:
        return {"forecasts": [], "stats": {"total": 0, "pending": 0, "resolved": 0, "mean_brier": None}, "producer_stats": []}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Check table exists
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if "forecast_calibration" not in tables:
        conn.close()
        return {"forecasts": [], "stats": {"total": 0, "pending": 0, "resolved": 0, "mean_brier": None}, "producer_stats": []}

    # Stats (always unfiltered)
    all_rows = conn.execute("SELECT * FROM forecast_calibration ORDER BY emitted_at DESC").fetchall()
    all_dicts = [dict(r) for r in all_rows]
    total = len(all_dicts)
    pending = sum(1 for r in all_dicts if r.get("outcome") is None)
    resolved = total - pending
    brier_vals = [r["brier_score"] for r in all_dicts if r.get("brier_score") is not None]
    mean_brier = sum(brier_vals) / len(brier_vals) if brier_vals else None

    # Filtered query
    conditions = []
    params: list[Any] = []
    if asset:
        conditions.append("asset = ?")
        params.append(asset)
    if horizon:
        conditions.append("horizon = ?")
        params.append(horizon)
    if status == "pending":
        conditions.append("outcome IS NULL")
    elif status == "resolved":
        conditions.append("outcome IS NOT NULL")

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = conn.execute(f"SELECT * FROM forecast_calibration{where} ORDER BY emitted_at DESC", params).fetchall()
    forecasts = [dict(r) for r in rows]

    # Per-producer stats
    from collections import defaultdict

    by_producer: dict[str, list[dict]] = defaultdict(list)
    for r in all_dicts:
        by_producer[r["producer_name"]].append(r)

    producer_stats = []
    for name, prows in sorted(by_producer.items()):
        p_resolved = [r for r in prows if r.get("outcome") is not None]
        p_correct = sum(1 for r in p_resolved if r.get("outcome") in ("correct", 1))
        p_brier = [r["brier_score"] for r in p_resolved if r.get("brier_score") is not None]
        producer_stats.append(
            {
                "name": name,
                "total": len(prows),
                "resolved": len(p_resolved),
                "accuracy": (p_correct / len(p_resolved) * 100) if p_resolved else None,
                "mean_brier": sum(p_brier) / len(p_brier) if p_brier else None,
            }
        )

    conn.close()
    return {
        "forecasts": forecasts,
        "stats": {"total": total, "pending": pending, "resolved": resolved, "mean_brier": mean_brier},
        "producer_stats": producer_stats,
    }


def _query_discretionary_signals() -> list[dict[str, Any]]:
    """Query active discretionary signals from brain.db."""
    db_path = _get_brain_db()
    if not db_path:
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if "discretionary_signals" not in tables:
        conn.close()
        return []

    rows = conn.execute("SELECT * FROM discretionary_signals WHERE expires_at > datetime('now') ORDER BY created_at DESC").fetchall()
    signals = [dict(r) for r in rows]
    conn.close()
    return signals


@app.post("/api/v1/signals/discretionary", response_class=HTMLResponse)
async def submit_discretionary_signal(request: Request) -> HTMLResponse:
    """Submit a discretionary signal via form or JSON."""
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        data = await request.json()
    else:
        form = await request.form()
        data = dict(form)

    symbol = str(data.get("symbol", "")).upper().strip()
    direction = str(data.get("direction", "")).lower().strip()
    notes = str(data.get("notes") or data.get("reasoning") or "")
    try:
        confidence = float(data.get("confidence", 5))
        # Normalize: form sends 1-10, DB stores 0.0-1.0
        if confidence > 1:
            confidence = confidence / 10.0
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = 0.5

    if not symbol:
        return HTMLResponse('<span class="text-warn">⚠ Asset symbol required</span>')
    if direction not in ("long", "short", "flat", "bullish", "bearish", "neutral"):
        return HTMLResponse('<span class="text-warn">⚠ Direction must be long/short/flat</span>')

    # Map aliases
    if direction == "bullish":
        direction = "long"
    elif direction == "bearish":
        direction = "short"
    elif direction == "neutral":
        direction = "flat"

    db_path = _get_brain_db()
    if not db_path:
        return HTMLResponse('<span class="text-warn">⚠ Brain DB not found</span>')

    try:
        with sqlite3.connect(str(db_path)) as conn:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            if "discretionary_signals" not in tables:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS discretionary_signals ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "symbol TEXT NOT NULL, "
                    "direction TEXT NOT NULL, "
                    "confidence REAL, "
                    "reasoning TEXT, "
                    "created_at TEXT DEFAULT (datetime('now')), "
                    "expires_at TEXT DEFAULT (datetime('now', '+24 hours')))"
                )

            conn.execute(
                "INSERT INTO discretionary_signals"
                " (symbol, direction, confidence, reasoning, created_at, expires_at)"
                " VALUES (?, ?, ?, ?, datetime('now'), datetime('now', '+24 hours'))",
                (symbol, direction, confidence, notes),
            )
    except Exception as e:
        return HTMLResponse(f'<span class="text-warn">⚠ DB error: {e}</span>')

    return HTMLResponse(f'<span class="text-bull">✓ {symbol} {direction} @ {confidence:.0%} submitted</span>')


@app.get("/forecasts", response_class=HTMLResponse)
def forecasts_page(
    request: Request,
    bundle: str | None = None,
    asset_class: str | None = None,
    venue: str | None = None,
    tag: str | None = None,
) -> HTMLResponse:
    """Forecasts page — grouped asset cards from conviction_scores."""
    from collections import defaultdict
    from datetime import UTC as _UTC2
    from datetime import datetime as _dt2

    client = _api(request)
    universe_ctx = _universe_bundle_context(client)

    bundle_symbol_map = {k: set(v) for k, v in universe_ctx.get("bundle_symbol_map", {}).items()}
    asset_class_symbol_map = {k: set(v) for k, v in universe_ctx.get("asset_class_symbol_map", {}).items()}
    venue_symbol_map = {k: set(v) for k, v in universe_ctx.get("venue_symbol_map", {}).items()}
    tag_symbol_map = {k: set(v) for k, v in universe_ctx.get("tag_symbol_map", {}).items()}

    asset_groups: list[dict] = []

    try:
        db_path = _get_brain_db()
        if db_path and db_path.exists():
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row

            # Only show symbols in the active universe that have data within 48h
            _active_syms: list[str] = []
            try:
                _cfg = getattr(getattr(app, "state", None), "config", None)
                if _cfg:
                    _active_syms = [s.upper() for s in _cfg.universe.active_symbols()]
            except Exception:
                pass

            if _active_syms:
                _ph = ",".join("?" * len(_active_syms))
                latest = conn.execute(
                    f"""
                    SELECT cs.*
                    FROM conviction_scores cs
                    INNER JOIN (
                        SELECT symbol, MAX(ts) as max_ts
                        FROM conviction_scores GROUP BY symbol
                    ) l ON cs.symbol = l.symbol AND cs.ts = l.max_ts
                    WHERE cs.symbol IN ({_ph})
                      AND cs.ts >= datetime('now', '-48 hours')
                    ORDER BY cs.confidence DESC
                    """,
                    _active_syms,
                ).fetchall()
            else:
                latest = conn.execute(
                    """
                    SELECT cs.*
                    FROM conviction_scores cs
                    INNER JOIN (
                        SELECT symbol, MAX(ts) as max_ts
                        FROM conviction_scores GROUP BY symbol
                    ) l ON cs.symbol = l.symbol AND cs.ts = l.max_ts
                    WHERE cs.ts >= datetime('now', '-48 hours')
                    ORDER BY cs.confidence DESC
                    """
                ).fetchall()

            all_rows = conn.execute(
                """
                SELECT symbol, direction, confidence, magnitude, timeframe, ts
                FROM conviction_scores
                WHERE ts >= datetime('now', '-24 hours')
                ORDER BY ts DESC
                """
            ).fetchall()
            conn.close()

            by_asset: dict[str, list[dict]] = defaultdict(list)
            for row in all_rows:
                by_asset[row["symbol"]].append(dict(row))

            for row in latest:
                asset = str(row["symbol"] or "").upper()
                if not asset:
                    continue

                direction = row["direction"] or "neutral"
                if direction in ("long", "buy"):
                    direction = "bullish"
                elif direction in ("short", "sell"):
                    direction = "bearish"
                confidence = float(row["confidence"] or 0)

                horizons_map: dict[str, dict] = {}
                for f in by_asset.get(asset, []):
                    tf = f.get("timeframe") or "—"
                    if tf not in horizons_map or (f.get("ts") or "") > (horizons_map[tf].get("ts") or ""):
                        horizons_map[tf] = f
                horizons = sorted(
                    horizons_map.values(),
                    key=lambda x: {"4h": 0, "24h": 1, "3d": 2}.get(x.get("timeframe") or "", 3),
                )

                age = "—"
                try:
                    dt = _dt2.fromisoformat(str(row["ts"]).replace("Z", "+00:00"))
                    secs = (_dt2.now(_UTC2) - dt).total_seconds()
                    age = f"{int(secs / 3600)}h ago" if secs >= 3600 else f"{int(secs / 60)}m ago"
                except Exception:
                    pass

                forecasts = []
                for f in by_asset.get(asset, [])[:10]:
                    emitted = (f.get("ts") or "—")[:16]
                    f_dir = f.get("direction") or "neutral"
                    if f_dir in ("long", "buy"):
                        f_dir = "bullish"
                    elif f_dir in ("short", "sell"):
                        f_dir = "bearish"
                    forecasts.append(
                        {
                            "producer_id": "brain",
                            "direction": f_dir,
                            "confidence": float(f.get("confidence") or 0),
                            "horizon": f.get("timeframe") or "—",
                            "emitted": emitted,
                        }
                    )

                asset_groups.append(
                    {
                        "asset": asset,
                        "direction": direction,
                        "max_confidence": confidence,
                        "horizons": [{"horizon": h.get("timeframe") or "—", "confidence": float(h.get("confidence") or 0)} for h in horizons],
                        "producers": [{"name": "brain", "domain": "events"}],
                        "age": age,
                        "forecasts": forecasts,
                    }
                )
    except Exception:
        pass

    # Apply bundle-aware filters (same model as signals page)
    if bundle:
        allowed = bundle_symbol_map.get(bundle)
        asset_groups = [g for g in asset_groups if g.get("asset") in allowed] if allowed else []

    if asset_class:
        allowed = asset_class_symbol_map.get(asset_class)
        asset_groups = [g for g in asset_groups if g.get("asset") in allowed] if allowed else []

    if venue:
        allowed = venue_symbol_map.get(venue)
        asset_groups = [g for g in asset_groups if g.get("asset") in allowed] if allowed else []

    if tag:
        allowed = tag_symbol_map.get(tag)
        asset_groups = [g for g in asset_groups if g.get("asset") in allowed] if allowed else []

    summary = {
        "total": sum(len(g.get("forecasts", [])) for g in asset_groups),
        "pending": sum(len(g.get("forecasts", [])) for g in asset_groups),
        "resolved": 0,
        "assets": len(asset_groups),
        "bullish": sum(1 for g in asset_groups if g.get("direction") == "bullish"),
        "bearish": sum(1 for g in asset_groups if g.get("direction") == "bearish"),
        "neutral": sum(1 for g in asset_groups if g.get("direction") not in {"bullish", "bearish"}),
    }

    enabled_ids = set(universe_ctx.get("enabled_bundle_ids") or [])
    raw_bundles: list[Any] = universe_ctx.get("bundles") if isinstance(universe_ctx.get("bundles"), list) else []
    bundle_options = [b for b in raw_bundles if isinstance(b, dict) and str(b.get("id") or "") and (not enabled_ids or str(b.get("id")) in enabled_ids)]
    bundle_options = sorted(bundle_options, key=lambda b: str(b.get("name") or b.get("id") or ""))

    return templates.TemplateResponse(
        request=request,
        name="forecasts.html",
        context={
            **_shell(request, "forecasts"),
            "asset_groups": asset_groups,
            "summary": summary,
            "bundle_options": bundle_options,
            "asset_class_options": universe_ctx.get("asset_classes", []),
            "venue_options": universe_ctx.get("venues", []),
            "tag_options": universe_ctx.get("tags", []),
            "active_bundle": bundle,
            "active_asset_class": asset_class,
            "active_venue": venue,
            "active_tag": tag,
        },
    )


@app.get("/partials/forecasts-table", response_class=HTMLResponse)
def forecasts_table_partial(request: Request, asset: str | None = None, horizon: str | None = None, status: str = "pending") -> HTMLResponse:
    data = _query_forecasts(asset=asset, horizon=horizon, status=status)
    return templates.TemplateResponse(
        request=request,
        name="partials/forecasts_table_inner.html",
        context={"request": request, "forecasts": data["forecasts"]},
    )


@app.get("/partials/discretionary-signals", response_class=HTMLResponse)
def discretionary_signals_partial(request: Request) -> HTMLResponse:
    signals = _query_discretionary_signals()
    return templates.TemplateResponse(
        request=request,
        name="partials/discretionary_signals_inner.html",
        context={"request": request, "disc_signals": signals},
    )


@app.get("/signals", response_class=HTMLResponse)
def signals_page(
    request: Request,
    domain: str | None = None,
    bundle: str | None = None,
    asset_class: str | None = None,
    venue: str | None = None,
    tag: str | None = None,
) -> HTMLResponse:
    client = _api(request)
    res = client.get_signals(domain=domain)
    signals = _map_signals(res.data)

    universe_ctx = _universe_bundle_context(client)

    bundle_symbol_map = {k: set(v) for k, v in universe_ctx.get("bundle_symbol_map", {}).items()}
    asset_class_symbol_map = {k: set(v) for k, v in universe_ctx.get("asset_class_symbol_map", {}).items()}
    venue_symbol_map = {k: set(v) for k, v in universe_ctx.get("venue_symbol_map", {}).items()}
    tag_symbol_map = {k: set(v) for k, v in universe_ctx.get("tag_symbol_map", {}).items()}

    if bundle:
        allowed = bundle_symbol_map.get(bundle)
        signals = [s for s in signals if s.get("symbol") in allowed] if allowed else []

    if asset_class:
        allowed = asset_class_symbol_map.get(asset_class)
        signals = [s for s in signals if s.get("symbol") in allowed] if allowed else []

    if venue:
        allowed = venue_symbol_map.get(venue)
        if allowed:
            signals = [s for s in signals if s.get("symbol") in allowed or str(s.get("venue") or "") == venue]
        else:
            signals = [s for s in signals if str(s.get("venue") or "") == venue]

    if tag:
        allowed = tag_symbol_map.get(tag)
        signals = [s for s in signals if s.get("symbol") in allowed] if allowed else []

    # Build latest-by-domain groups from filtered signals.
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for s in signals:
        by_domain.setdefault(str(s.get("domain") or "unknown"), []).append(s)

    try:
        _universe_total = len(list(app.state.config.universe.active_symbols()))
    except Exception:
        _universe_total = 0
    domain_groups = []
    for d, items in sorted(by_domain.items()):
        covered = sorted({str(s.get("symbol") or s.get("asset") or "").upper() for s in items if s.get("symbol") or s.get("asset")})
        domain_groups.append(
            {
                "domain": d,
                "age": "—" if res.ok else "stale",
                "signals": items[:4],
                "symbol_count": len(covered),
                "symbol_list": ", ".join(covered[:8]) + ("…" if len(covered) > 8 else ""),
            }
        )

    domains = [
        {"id": "ta", "label": "TA"},
        {"id": "tradfi", "label": "TradFi"},
        {"id": "onchain", "label": "Onchain"},
        {"id": "social", "label": "Social"},
        {"id": "sentiment", "label": "Sentiment"},
        {"id": "events", "label": "Events"},
        {"id": "aci", "label": "ACI"},
        {"id": "research", "label": "Research"},
    ]

    filter_params: dict[str, str] = {}
    if bundle:
        filter_params["bundle"] = bundle
    if asset_class:
        filter_params["asset_class"] = asset_class
    if venue:
        filter_params["venue"] = venue
    if tag:
        filter_params["tag"] = tag
    filter_qs = urlencode(filter_params)

    enabled_ids = set(universe_ctx.get("enabled_bundle_ids") or [])
    raw_bundles: list[Any] = universe_ctx.get("bundles") if isinstance(universe_ctx.get("bundles"), list) else []
    bundle_options = [b for b in raw_bundles if isinstance(b, dict) and str(b.get("id") or "") and (not enabled_ids or str(b.get("id")) in enabled_ids)]
    bundle_options = sorted(bundle_options, key=lambda b: str(b.get("name") or b.get("id") or ""))

    now_dt = datetime.now(tz=UTC)
    timeline_window_label = f"{(now_dt - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M')} → {now_dt.strftime('%Y-%m-%d %H:%M')} UTC"
    latest_dt: datetime | None = None
    for s in signals:
        dt = _parse_dt(s.get("ts_iso") or s.get("ts"))
        if dt is None:
            continue
        if latest_dt is None or dt > latest_dt:
            latest_dt = dt
    latest_signal_ts = latest_dt.isoformat() if latest_dt is not None else None
    latest_signal_age = _timeago_filter(latest_signal_ts) if latest_signal_ts else "none"
    # Freshness is a market primitive: stale timestamps manufacture false certainty.
    # Surface drift before anyone mistakes delayed data for conviction.
    signal_feed_stale = bool(latest_dt and (now_dt - latest_dt).total_seconds() > 1800)

    return templates.TemplateResponse(
        request=request,
        name="signals.html",
        context={
            **_shell(request, "signals"),
            "domains": domains,
            "active_domain": domain,
            "signals": signals,
            "total_signals": len(signals),
            "domain_groups": domain_groups,
            "bundle_options": bundle_options,
            "asset_class_options": universe_ctx.get("asset_classes", []),
            "venue_options": universe_ctx.get("venues", []),
            "tag_options": universe_ctx.get("tags", []),
            "active_bundle": bundle,
            "active_asset_class": asset_class,
            "active_venue": venue,
            "active_tag": tag,
            "domain_filter_suffix": f"&{filter_qs}" if filter_qs else "",
            "all_filter_query": f"?{filter_qs}" if filter_qs else "",
            "timeline_window_label": timeline_window_label,
            "latest_signal_ts": latest_signal_ts,
            "latest_signal_age": latest_signal_age,
            "signal_feed_stale": signal_feed_stale,
        },
    )


@app.get("/social", response_class=HTMLResponse)
def social_page(request: Request) -> HTMLResponse:
    client = _api(request)

    status_res = client.get_social_status()
    status_data = status_res.data if (status_res.ok and isinstance(status_res.data, dict)) else {}

    sent_res = client.get_social_sentiment()
    alerts_res = client.get_social_alerts()
    nar_res = client.get_social_narratives()
    src_res = client.get_social_sources()
    cur_res = client.get_curator_feed()
    coll_res = client.get_collector_health()

    sentiments = sent_res.data.get("items") if (sent_res.ok and isinstance(sent_res.data, dict)) else []
    alerts = alerts_res.data.get("items") if (alerts_res.ok and isinstance(alerts_res.data, dict)) else []
    narratives = nar_res.data.get("items") if (nar_res.ok and isinstance(nar_res.data, dict)) else []
    sources = src_res.data.get("items") if (src_res.ok and isinstance(src_res.data, dict)) else []
    curator_signals = cur_res.data.get("items") if (cur_res.ok and isinstance(cur_res.data, dict)) else []

    art_res = client.get_artifacts(limit=5)
    recent_artifacts = art_res.data.get("items") if (art_res.ok and isinstance(art_res.data, dict)) else []

    pipeline_status = str(status_data.get("pipeline_status", "unknown"))
    pipeline_active = bool(status_data.get("pipeline_active", False))
    diagnosis = str(status_data.get("diagnosis", "Unable to reach social status API"))
    actions_available = status_data.get("actions_available", [])
    producer_health = status_data.get("producers", [])
    watchlist = status_data.get("watchlist", [])
    seeded = bool(status_data.get("seeded", False))
    watchlist_count = int(status_data.get("watchlist_count", 0) or 0)
    sources_configured = int(status_data.get("sources_configured", 0) or 0)
    signal_events_count = int(status_data.get("signal_events_count", 0) or 0)
    failing_producers = int(status_data.get("failing_producers", 0) or 0)

    pipeline_last_run = "never"
    newest_run: datetime | None = None
    for p in producer_health if isinstance(producer_health, list) else []:
        if not isinstance(p, dict) or not p.get("last_run_at"):
            continue
        try:
            dt = datetime.fromisoformat(str(p["last_run_at"]).replace("Z", "+00:00"))
            if newest_run is None or dt > newest_run:
                newest_run = dt
        except Exception:
            continue
    if newest_run is not None:
        pipeline_last_run, _ = _age_str(newest_run)

    social_empty_reason = diagnosis
    if pipeline_status == "unconfigured":
        if watchlist_count == 0:
            social_empty_reason = "No watchlist configured yet. Seed defaults or add symbols manually."
        elif sources_configured == 0:
            social_empty_reason = "No social sources configured yet. Add at least one source to start collection."
    elif pipeline_status == "running_no_data":
        social_empty_reason = "Pipeline is running, but no social signal events have been produced yet."
    elif pipeline_status in {"degraded", "down"}:
        social_empty_reason = "Social pipeline is degraded. Inspect producer failures and collector health below."
    elif not sent_res.ok:
        social_empty_reason = "Sentiment API unavailable right now."

    sentiment_horizons = _get_sentiment_horizons()

    collector_data = coll_res.data if (coll_res.ok and isinstance(coll_res.data, dict)) else {}

    return templates.TemplateResponse(
        request=request,
        name="social.html",
        context={
            **_shell(request, "social"),
            "pipeline_active": pipeline_active,
            "pipeline_status": pipeline_status,
            "pipeline_last_run": pipeline_last_run,
            "diagnosis": diagnosis,
            "actions_available": actions_available if isinstance(actions_available, list) else [],
            "producer_health": producer_health if isinstance(producer_health, list) else [],
            "watchlist": watchlist if isinstance(watchlist, list) else [],
            "seeded": seeded,
            "watchlist_count": watchlist_count,
            "sources_configured": sources_configured,
            "signal_events_count": signal_events_count,
            "failing_producers": failing_producers,
            "social_empty_reason": social_empty_reason,
            "llm_cost": 0.0,
            "llm_budget": 100,
            "llm_cost_pct": 0.0,
            "social_kill": False,
            "sources_brief": [],
            "sentiment_age": "—" if sent_res.ok else "stale",
            "sources_active": sources_configured,
            "sentiments": sentiments if isinstance(sentiments, list) else [],
            "alerts": alerts if isinstance(alerts, list) else [],
            "narratives": narratives if isinstance(narratives, list) else [],
            "curator_signals": curator_signals if isinstance(curator_signals, list) else [],
            "sources": sources if isinstance(sources, list) else [],
            "source_warnings": [],
            "recent_artifacts": recent_artifacts if isinstance(recent_artifacts, list) else [],
            "sentiment_horizons": sentiment_horizons,
            "collectors": collector_data.get("collectors", []),
            "collector_summary": collector_data.get("summary", {}),
            "collector_health_ok": coll_res.ok,
        },
    )


@app.get("/artifacts", response_class=HTMLResponse)
def artifacts_page(request: Request) -> HTMLResponse:
    client = _api(request)
    art_res = client.get_artifacts(limit=50)
    artifacts = art_res.data.get("items") if (art_res.ok and isinstance(art_res.data, dict)) else []

    return templates.TemplateResponse(
        request=request,
        name="artifacts.html",
        context={
            **_shell(request, "artifacts"),
            "artifacts": artifacts if isinstance(artifacts, list) else [],
        },
    )


@app.get("/performance", response_class=HTMLResponse)
def performance_page(request: Request) -> HTMLResponse:
    # Pull real performance data from DB
    perf: dict[str, Any] = {
        "total_trades": 0,
        "win_rate": None,
        "avg_pnl": None,
        "total_pnl": 0.0,
        "sharpe": None,
        "max_drawdown": None,
        "closed_positions": [],
        "open_positions": [],
    }
    try:
        db_path = _get_brain_db()
        if db_path is not None:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            closed = conn.execute(
                "SELECT asset, direction, entry_price, realized_pnl, size_notional, opened_at, closed_at "
                "FROM positions WHERE status='closed' ORDER BY closed_at DESC"
            ).fetchall()
            open_pos = conn.execute(
                "SELECT asset, direction, entry_price, size_notional, stop_loss, take_profit, opened_at "
                "FROM positions WHERE status='open' ORDER BY opened_at DESC"
            ).fetchall()
            conn.close()

            closed_list = [dict(r) for r in closed]
            pnls = [r["realized_pnl"] for r in closed_list if r["realized_pnl"] is not None]
            wins = [p for p in pnls if p > 0]
            total_pnl = sum(pnls)

            # Equity curve: cumulative PnL per trade
            equity: list[dict] = []
            cumulative = 0.0
            for r in reversed(closed_list):
                if r["realized_pnl"] is not None:
                    cumulative += r["realized_pnl"]
                    equity.append({"label": r["asset"], "value": round(cumulative, 4)})

            perf.update(
                {
                    "total_trades": len(pnls),
                    "win_rate": round(len(wins) / len(pnls) * 100, 1) if pnls else None,
                    "avg_pnl": round(sum(pnls) / len(pnls), 2) if pnls else None,
                    "total_pnl": round(total_pnl, 4),
                    "closed_positions": closed_list,
                    "trades": [
                        {
                            "id": r.get("asset", "")[:6],
                            "asset": r.get("asset", ""),
                            "direction": r.get("direction", ""),
                            "entry": r.get("entry_price") or 0,
                            "exit": (r.get("entry_price") or 0) + ((r.get("realized_pnl") or 0) / (r.get("size_notional") or 1)) * (r.get("entry_price") or 1),
                            "pnl": r.get("realized_pnl") or 0,
                            "held": r.get("opened_at", "")[:10],
                        }
                        for r in closed_list
                    ],
                    "open_positions": [dict(r) for r in open_pos],
                    "equity_curve": equity,
                }
            )
    except Exception as _e:
        pass

    return templates.TemplateResponse(
        request=request,
        name="performance.html",
        context={**_shell(request, "performance"), **perf},
    )


@app.get("/system", response_class=HTMLResponse)
def system_page_redirect(request: Request) -> Response:
    """System merged into Settings — redirect for backward compat."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/settings", status_code=302)


@app.post("/api/settings/universe/tradfi", response_class=HTMLResponse)
def settings_tradfi_symbols(request: Request, symbols: str = Form("")) -> HTMLResponse:
    """Save TradFi symbols list to user config via API (triggers hot-reload)."""
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    try:
        client = _api(request)
        # Fetch current config, merge tradfi_symbols, POST back via API so daemon hot-reloads
        cfg_res = client._get_json("/config")
        cfg_data: dict[str, Any] = {}
        if cfg_res.ok and isinstance(cfg_res.data, dict):
            # Strip redacted sentinel values so we don't overwrite real secrets with "***REDACTED***"
            import copy as _copy

            cfg_data = _copy.deepcopy(cfg_res.data)
            for _section in cfg_data.values():
                if not isinstance(_section, dict):
                    continue
                for _k, _v in list(_section.items()):
                    if isinstance(_v, str) and _v == "***REDACTED***":
                        del _section[_k]
        cfg_data.setdefault("universe", {})["tradfi_symbols"] = sym_list
        save_res = client._post_json("/config", cfg_data)
        if save_res.ok:
            status_ok, status_msg = True, f"Saved {len(sym_list)} TradFi symbols"
        else:
            # Fallback: write yaml directly if API unavailable
            import yaml as _yaml

            cfg_path = Path(os.environ.get("B1E55ED_CONFIG_PATH", os.path.expanduser("~/.b1e55ed/config/user.yaml")))
            raw: dict[str, Any] = {}
            if cfg_path.exists():
                with open(cfg_path) as f:
                    raw = _yaml.safe_load(f) or {}
            raw.setdefault("universe", {})["tradfi_symbols"] = sym_list
            with open(cfg_path, "w") as f:
                _yaml.dump(raw, f, default_flow_style=False)
            status_ok, status_msg = True, f"Saved {len(sym_list)} TradFi symbols (yaml fallback)"
    except Exception as e:
        status_ok, status_msg = False, str(e)

    return templates.TemplateResponse(
        request=request,
        name="partials/_tradfi_panel.html",
        context={
            "request": request,
            "tradfi_symbols": sym_list,
            "tradfi_twelvedata_key_set": bool(os.environ.get("B1E55ED_TWELVEDATA_KEY")),
            "tradfi_status_ok": status_ok,
            "tradfi_status_msg": status_msg,
        },
    )


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request) -> HTMLResponse:
    client = _api(request)
    universe_ctx = _universe_bundle_context(client)
    cfg_res = client._get_json("/config")
    cfg = cfg_res.data if (cfg_res.ok and isinstance(cfg_res.data, dict)) else {}

    # Ensure nested dicts exist for template access
    cfg.setdefault("risk", {})
    cfg.setdefault("brain", {})
    cfg.setdefault("execution", {})
    cfg.setdefault("karma", {})

    risk = cfg.get("risk", {})
    trading_mode = cfg.get("execution", {}).get("mode", "paper")

    risk_fields = [
        {"key": "max_daily_loss", "label": "Max Daily Loss (USD)", "value": risk.get("max_daily_loss", 500), "step": "50"},
        {"key": "max_position_size", "label": "Max Position Size (%)", "value": risk.get("max_position_size", 10), "step": "1"},
        {"key": "max_leverage", "label": "Max Leverage", "value": risk.get("max_leverage", 5), "step": "1"},
    ]

    api_key_names = [
        "HYPERLIQUID_PRIVATE_KEY",
        "NANSEN_API_KEY",
        "ALLIUM_API_KEY",
        "OPENAI_API_KEY",
    ]
    api_keys = [{"name": k, "configured": bool(os.environ.get(k, "").strip())} for k in api_key_names]

    # Surface the API auth token for settings display
    _raw_token = str((cfg.get("api") or {}).get("auth_token", "") or os.environ.get("B1E55ED_API_TOKEN", "") or "")
    _token_display = (_raw_token[:8] + "..." + _raw_token[-4:]) if len(_raw_token) > 12 else (_raw_token if _raw_token else "not set")
    api_auth_token_info = {
        "configured": bool(_raw_token),
        "display": _token_display,
        "hint": "Set via api.auth_token in user.yaml or B1E55ED_API_TOKEN env var",
    }

    # Producer config discovery: collect configurable_fields from all producers
    producer_configs: list[dict[str, Any]] = []
    try:
        from engine.producers.registry import discover as _discover
        from engine.producers.registry import get_producer as _get_reg
        from engine.producers.registry import list_producers as _list_reg

        _discover()
        for pname in _list_reg():
            cls = _get_reg(pname)
            fields = getattr(cls, "configurable_fields", None)
            if not fields:
                continue
            enriched_fields = []
            for f in fields:
                key = f.get("key", "")
                raw_val = os.environ.get(key, "").strip()
                is_sensitive = any(s in key.lower() for s in ("key", "secret", "token", "password", "private"))
                enriched_fields.append(
                    {
                        **f,
                        "configured": bool(raw_val),
                        "display_value": ("••••" + raw_val[-4:]) if (raw_val and is_sensitive) else (raw_val or ""),
                        "is_sensitive": is_sensitive,
                    }
                )
            producer_configs.append(
                {
                    "name": pname,
                    "domain": getattr(cls, "domain", "—"),
                    "fields": enriched_fields,
                }
            )
    except Exception:
        pass

    # System data (merged from /system page)
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

            producers.append(
                {
                    "name": str(name),
                    "domain": v.get("domain") or "—",
                    "health": health,
                    "last_run": last_run,
                }
            )

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
        request=request,
        name="settings.html",
        context={
            **_shell(request, "settings", kill_switch_level=ks_level),
            "trading_mode": trading_mode,
            "risk_fields": risk_fields,
            "api_keys": api_keys,
            "api_auth_token_info": api_auth_token_info,
            "producer_configs": producer_configs,
            # Config page data
            "preset": "custom",
            "presets": ["conservative", "balanced", "degen"],
            "cfg": cfg,
            "universe_bundles": universe_ctx.get("bundles", []),
            "universe_packs": universe_ctx.get("packs", []),
            "universe_pack_map": universe_ctx.get("pack_map", {}),
            "universe_active_symbols": universe_ctx.get("active_symbols", []),
            "tradfi_symbols": (cfg.get("universe") or {}).get("tradfi_symbols") or [],
            "tradfi_twelvedata_key_set": bool(os.environ.get("B1E55ED_TWELVEDATA_KEY")),
            "universe_fallback_to_symbols": universe_ctx.get("fallback_to_symbols", True),
            # System page data
            "producers": producers,
            "producers_healthy": producers_healthy,
            "producers_total": len(producers),
            "kill_switch_level": ks_level,
            "kill_switch_label": label,
            "kill_switch_last_change": kill_last_change,
            **_system_status_ctx(),
        },
    )


def _render_universe_bundles_panel(
    request: Request,
    *,
    status_message: str | None = None,
    status_ok: bool = False,
) -> HTMLResponse:
    ctx = _universe_bundle_context(_api(request))
    return templates.TemplateResponse(
        request=request,
        name="partials/universe_bundles_panel.html",
        context={
            "request": request,
            "universe_bundles": ctx.get("bundles", []),
            "universe_packs": ctx.get("packs", []),
            "universe_pack_map": ctx.get("pack_map", {}),
            "universe_active_symbols": ctx.get("active_symbols", []),
            "universe_fallback_to_symbols": ctx.get("fallback_to_symbols", True),
            "bundle_status_message": status_message,
            "bundle_status_ok": status_ok,
        },
    )


@app.get("/partials/universe-bundles", response_class=HTMLResponse)
def universe_bundles_partial(request: Request) -> HTMLResponse:
    return _render_universe_bundles_panel(request)


@app.post("/api/settings/universe/bundles", response_class=HTMLResponse)
async def settings_add_universe_bundle(request: Request) -> HTMLResponse:
    form = await request.form()

    pack_id = str(form.get("pack_id") or "").strip().lower() or None
    name = str(form.get("name") or "").strip()
    symbols_raw = str(form.get("symbols") or "")
    tags_raw = str(form.get("tags") or "")

    asset_class_raw = str(form.get("asset_class") or "").strip()
    venue_raw = str(form.get("venue") or "").strip()

    enabled = str(form.get("enabled") or "true").strip().lower() in {"1", "true", "yes", "on"}

    symbols = [s.strip().upper() for s in symbols_raw.replace("\n", ",").split(",") if s.strip()]
    tags = [t.strip().lower() for t in tags_raw.replace("\n", ",").split(",") if t.strip()]

    if not pack_id and not name:
        return _render_universe_bundles_panel(request, status_message="Bundle name is required.", status_ok=False)
    if not pack_id and not symbols:
        return _render_universe_bundles_panel(request, status_message="At least one symbol is required.", status_ok=False)

    payload: dict[str, Any] = {
        "pack_id": pack_id,
        "name": name or None,
        "symbols": symbols or None,
        "tags": tags or None,
        "asset_class": asset_class_raw or None,
        "venue": venue_raw or None,
        "enabled": enabled,
        "source": "user",
    }

    if not pack_id:
        payload["asset_class"] = asset_class_raw or "crypto"
        payload["venue"] = venue_raw or "global"

    result = _api(request).create_universe_bundle(payload)

    if not result.ok:
        msg = f"Failed to add bundle{' from pack' if pack_id else ''} (API unavailable)."
        return _render_universe_bundles_panel(request, status_message=msg, status_ok=False)

    created = result.data if isinstance(result.data, dict) else {}
    label = str(created.get("name") or name or pack_id or "bundle")
    return _render_universe_bundles_panel(request, status_message=f"Added bundle: {label}", status_ok=True)


@app.post("/api/settings/universe/bundles/{bundle_id}/toggle", response_class=HTMLResponse)
async def settings_toggle_universe_bundle(bundle_id: str, request: Request) -> HTMLResponse:
    form = await request.form()
    enabled = str(form.get("enabled") or "").strip().lower() in {"1", "true", "yes", "on"}

    result = _api(request).update_universe_bundle(bundle_id, {"enabled": enabled})
    if not result.ok:
        return _render_universe_bundles_panel(request, status_message=f"Failed to update bundle: {bundle_id}", status_ok=False)

    state = "enabled" if enabled else "disabled"
    return _render_universe_bundles_panel(request, status_message=f"{bundle_id} {state}", status_ok=True)


@app.post("/api/settings/universe/bundles/{bundle_id}/delete", response_class=HTMLResponse)
async def settings_delete_universe_bundle(bundle_id: str, request: Request) -> HTMLResponse:
    result = _api(request).delete_universe_bundle(bundle_id)
    if not result.ok:
        return _render_universe_bundles_panel(request, status_message=f"Failed to delete bundle: {bundle_id}", status_ok=False)

    return _render_universe_bundles_panel(request, status_message=f"Deleted bundle: {bundle_id}", status_ok=True)


def _settings_not_implemented(action: str) -> HTMLResponse:
    return HTMLResponse(f'<span class="text-warn" style="font-size:0.75rem;">⚠ {action} is not implemented from dashboard yet.</span>')


@app.post("/api/v1/brain/run", response_class=HTMLResponse)
async def dashboard_run_brain_cycle(request: Request) -> HTMLResponse:
    client = _api(request)
    result = client.run_brain_cycle()
    if result.ok and isinstance(result.data, dict):
        cycle_id = str(result.data.get("cycle_id") or "submitted")
        return HTMLResponse(f'<span class="text-bull" style="font-size:0.75rem;">✓ Cycle triggered ({cycle_id})</span>')

    return HTMLResponse('<span class="text-warn" style="font-size:0.75rem;">⚠ Run cycle failed — check API auth/connectivity.</span>')


@app.post("/api/kill-switch", response_class=HTMLResponse)
async def dashboard_set_kill_switch(request: Request, level: int | None = None) -> HTMLResponse:
    target_level = level

    if target_level is None:
        status = _api(request).get_kill_switch()
        current_level = 0
        if status.ok and isinstance(status.data, dict):
            with contextlib.suppress(TypeError, ValueError):
                current_level = int(status.data.get("kill_switch_level") or 0)
        target_level = 0 if current_level > 0 else 1

    if target_level < 0 or target_level > 4:
        return HTMLResponse('<span class="text-warn" style="font-size:0.75rem;">⚠ Kill-switch level must be 0–4.</span>')

    result = _kill_switch_api(request).set_kill_switch(level=target_level, reason="dashboard")
    if result.ok:
        return HTMLResponse(f'<span class="text-bull" style="font-size:0.75rem;">✓ Kill switch set to L{target_level}</span>')

    return HTMLResponse('<span class="text-warn" style="font-size:0.75rem;">⚠ Kill-switch update failed — verify kill-switch token/API availability.</span>')


@app.post("/api/settings/trading-mode", response_class=HTMLResponse)
async def settings_trading_mode(request: Request) -> HTMLResponse:
    form = await request.form()
    mode = str(form.get("mode", "paper")).strip().lower() or "paper"
    return _settings_not_implemented(f"Trading mode update ({mode.upper()})")


@app.post("/api/settings/risk/{field}", response_class=HTMLResponse)
async def settings_risk_field(field: str, request: Request) -> HTMLResponse:
    _ = await request.form()  # consume form data
    return _settings_not_implemented(f"Risk limit update ({field})")


@app.post("/api/settings/reset-defaults", response_class=HTMLResponse)
async def settings_reset_defaults(request: Request) -> HTMLResponse:
    _ = await request.body()
    return _settings_not_implemented("Reset defaults")


@app.post("/api/settings/clear-signals", response_class=HTMLResponse)
async def settings_clear_signals(request: Request) -> HTMLResponse:
    _ = await request.body()
    return _settings_not_implemented("Clear signal history")


@app.post("/api/settings/config/preset", response_class=HTMLResponse)
async def settings_config_preset(request: Request) -> HTMLResponse:
    form = await request.form()
    preset = str(form.get("preset") or "custom")
    return _settings_not_implemented(f"Preset switch ({preset})")


@app.get("/api/settings/config/reload", response_class=HTMLResponse)
def settings_config_reload() -> HTMLResponse:
    return _settings_not_implemented("Config reload")


@app.post("/api/settings/config/save", response_class=HTMLResponse)
async def settings_config_save(request: Request) -> HTMLResponse:
    _ = await request.form()
    return _settings_not_implemented("Config save")


@app.get("/partials/artifact-preview/{artifact_id}", response_class=HTMLResponse)
def artifact_preview(request: Request, artifact_id: str) -> HTMLResponse:
    client = _api(request)
    art_res = client.get_artifacts(limit=200)
    artifacts = art_res.data if (art_res.ok and isinstance(art_res.data, list)) else []

    artifact = None
    for a in artifacts:
        if isinstance(a, dict) and a.get("id") == artifact_id:
            artifact = a
            break

    if artifact is None:
        return HTMLResponse('<div class="text-dim" style="padding:1rem;">Artifact not found.</div>')

    # Try to fetch content for text-based artifacts
    content = None
    ct = (artifact.get("content_type") or "").lower()
    if "json" in ct or "text" in ct or "markdown" in ct or "yaml" in ct:
        content_res = client._get_json(f"/artifacts/{artifact_id}/content")
        if content_res.ok:
            import json as _json

            raw = content_res.data
            if isinstance(raw, (dict, list)):
                content = _json.dumps(raw, indent=2)[:5000]
            elif isinstance(raw, str):
                content = raw[:5000]

    artifact["content"] = content
    return templates.TemplateResponse(
        request=request,
        name="partials/artifact_preview.html",
        context={"request": request, "artifact": artifact},
    )


@app.post("/api/producers/{name}/restart", response_class=HTMLResponse)
@app.post("/api/v1/producers/{name}/restart", response_class=HTMLResponse)
async def restart_producer(name: str, request: Request) -> HTMLResponse:
    client = _api(request)
    result = client._post_json(f"/producers/{name}/restart", {})
    if result.ok:
        return HTMLResponse('<span class="text-bull">✓ Restarted</span>')
    return HTMLResponse('<span class="text-bear">✗ Failed</span>')


@app.post("/api/producers/{name}/reset-failures", response_class=HTMLResponse)
@app.post("/api/v1/producers/{name}/reset-failures", response_class=HTMLResponse)
async def reset_producer_failures(name: str, request: Request) -> HTMLResponse:
    client = _api(request)
    result = client._post_json(f"/producers/{name}/reset-failures", {})
    if result.ok:
        return HTMLResponse('<span class="text-bull">✓ Failures cleared</span>')
    return HTMLResponse('<span class="text-bear">✗ Failed</span>')


@app.post("/api/producers/{name}/run-now", response_class=HTMLResponse)
@app.post("/api/v1/producers/{name}/run-now", response_class=HTMLResponse)
async def run_producer_now(name: str, request: Request) -> HTMLResponse:
    client = _api(request)
    result = client._post_json(f"/producers/{name}/run-now", {})
    if result.ok:
        return HTMLResponse('<span class="text-bull">✓ Triggered</span>')
    return HTMLResponse('<span class="text-bear">✗ Failed</span>')


@app.post("/api/positions/{position_id}/close", response_class=HTMLResponse)
async def close_position_proxy(position_id: str, request: Request) -> HTMLResponse:
    """Proxy close-position to the API and return an HTMX status fragment."""
    form = await request.form()
    exit_price_raw = form.get("exit_price")
    body: dict = {"reason": "dashboard"}
    if exit_price_raw:
        with contextlib.suppress(ValueError, TypeError):
            body["exit_price"] = float(exit_price_raw)
    client = _api(request)
    result = client._post_json(f"/positions/{position_id}/close", body)
    if result.ok:
        pnl = ""
        if isinstance(result.data, dict):
            pnl_val = result.data.get("realized_pnl")
            if pnl_val is not None:
                with contextlib.suppress(TypeError, ValueError):
                    sign = "+" if float(pnl_val) >= 0 else ""
                    pnl = f" (PnL: {sign}${float(pnl_val):.2f})"
        closed_panel = (
            f'<div id="pos-panel-{position_id}" class="panel" '
            f'style="margin-bottom:1rem; opacity:0.5;">'
            f'<div class="panel-header">'
            f'<span class="panel-title text-dim">{position_id} — closed</span>'
            f'<span class="text-bull" style="font-size:0.85rem;">✓ Closed{pnl}</span>'
            f"</div></div>"
        )
        return HTMLResponse(
            closed_panel,
            headers={"HX-Trigger": "positionsRefresh"},
        )
    return HTMLResponse('<span class="text-bear">✗ Failed to close position</span>')


@app.post("/api/positions/{position_id}/adjust-stop", response_class=HTMLResponse)
async def adjust_stop(position_id: str, request: Request) -> HTMLResponse:
    form = await request.form()
    price = float(form.get("price", 0))
    client = _api(request)
    result = client._patch_json(f"/positions/{position_id}/stop", {"stop_loss": price})
    if result.ok:
        return HTMLResponse(f'<span class="text-bull">Stop set to ${price:.2f}</span>')
    return HTMLResponse('<span class="text-bear">Failed to set stop</span>')


@app.post("/api/positions/{position_id}/adjust-target", response_class=HTMLResponse)
async def adjust_target(position_id: str, request: Request) -> HTMLResponse:
    form = await request.form()
    price = float(form.get("price", 0))
    client = _api(request)
    result = client._patch_json(f"/positions/{position_id}/target", {"take_profit": price})
    if result.ok:
        return HTMLResponse(f'<span class="text-bull">Target set to ${price:.2f}</span>')
    return HTMLResponse('<span class="text-bear">Failed to set target</span>')


# ---- Karma settle proxy (3.5) --------------------------------------------


@app.post("/api/karma/settle", response_class=HTMLResponse)
async def karma_settle(request: Request) -> HTMLResponse:
    """Proxy karma settle to the API and return an HTMX fragment."""
    client = _api(request)
    result = client._post_json("/karma/settle", {})
    if result.ok:
        settled = ""
        if isinstance(result.data, dict):
            n = result.data.get("settled") or result.data.get("count")
            if n is not None:
                settled = f" ({n} settled)"
        return HTMLResponse(f'<span class="text-bull">✓ Karma settled{settled}</span>')
    return HTMLResponse('<span class="text-warn">⚠ Karma settle failed — check API availability.</span>')


# ---- Events verify-chain (3.6) -------------------------------------------


@app.post("/api/events/verify-chain", response_class=HTMLResponse)
async def events_verify_chain(request: Request) -> HTMLResponse:
    """Verify the brain.db event hash chain and return an HTMX fragment."""
    db_path = _get_brain_db()
    if not db_path:
        return HTMLResponse('<span class="text-warn">⚠ brain.db not found</span>')
    try:
        from engine.core.database import Database as _Database

        db = _Database(db_path)
        valid = db.verify_hash_chain(fast=True)
        db.close()
        # fast=True only checks recent events, not the full chain.
        # Report accurately to avoid misleading operators.
        fast_label = "recent events (fast mode)"
        if valid:
            return HTMLResponse(f'<span class="text-bull">✓ Chain valid — {fast_label} verified. Run <code>b1e55ed verify-chain</code> for full audit.</span>')
        return HTMLResponse(
            f'<span class="text-bear">✗ Chain INVALID — {fast_label} checked. Possible tampering. Run <code>b1e55ed verify-chain</code> for details.</span>'
        )
    except Exception as exc:
        return HTMLResponse(f'<span class="text-warn">⚠ Verify failed: {exc}</span>')


# ---- Events export (3.7) -------------------------------------------------


@app.get("/api/events/export")
async def events_export(request: Request) -> Response:
    """Export up to 10,000 recent events from brain.db as a JSON attachment."""
    import json as _json

    db_path = _get_brain_db()
    if not db_path:
        return HTMLResponse('<span class="text-warn">brain.db not found</span>', status_code=404)
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, type, payload, ts, source, trace_id, schema_version FROM events ORDER BY id DESC LIMIT 10000").fetchall()
        conn.close()
        # Reverse so oldest-first order in the export
        events = [dict(r) for r in reversed(rows)]
        body = _json.dumps({"count": len(events), "events": events}, default=str)
        return Response(
            content=body,
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="events.json"'},
        )
    except Exception as exc:
        return HTMLResponse(f'<span class="text-warn">Export failed: {exc}</span>', status_code=500)


@app.get("/config", response_class=HTMLResponse)
def config_page_redirect(request: Request) -> Response:
    """Config merged into Settings — redirect for backward compat."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/settings", status_code=302)


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
        request=request,
        name="treasury.html",
        context={
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


@app.get("/partials/conviction", response_class=HTMLResponse)
def conviction_partial(request: Request) -> HTMLResponse:
    client = _api(request)
    ctx = _build_conviction_ctx(client)
    return templates.TemplateResponse(request=request, name="partials/conviction_panel.html", context={"request": request, **ctx})


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

    html = f'<div class="kill-dot level-{level}" title="{title}" hx-get="/partials/kill-dot" hx-trigger="every 30s" hx-swap="outerHTML"></div>'
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

    html = f'<span class="regime-pill regime-{regime}" hx-get="/partials/regime-pill" hx-trigger="every 30s" hx-swap="outerHTML">{label}</span>'
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
    all_positions = _annotate_positions_with_convictions(_map_positions(res.data), client)
    # Brain panel is "open positions" context — hide closed rows.
    positions = [p for p in all_positions if str(p.get("status") or "").lower() != "closed"]

    return templates.TemplateResponse(
        request=request,
        name="partials/positions_panel.html",
        context={
            "request": request,
            "positions": positions,
            "positions_age": "—" if res.ok else "stale",
        },
    )


@app.get("/partials/position/{position_id}", response_class=HTMLResponse)
def position_partial(request: Request, position_id: str) -> HTMLResponse:
    client = _api(request)
    res = client.get_positions()
    positions = _annotate_positions_with_convictions(_map_positions(res.data), client)
    p = next((x for x in positions if x.get("id") == position_id), None)
    if p is None:
        return HTMLResponse('<div class="empty-state">Position not found.</div>')

    return templates.TemplateResponse(
        request=request,
        name="partials/position_detail_panel.html",
        context={"request": request, "p": p},
    )


@app.get("/partials/vitals-bar", response_class=HTMLResponse)
def vitals_bar_partial(request: Request) -> HTMLResponse:
    # "A purely peer-to-peer version of electronic cash would allow online payments
    # to be sent directly from one party to another without going through a financial
    # institution." — Satoshi Nakamoto, 2008. The vitals bar is the heartbeat
    # of a system built on that premise.
    import datetime as _dt

    db_path = _get_brain_db()
    last_signal_age = "—"
    producer_count = 0
    stale = False
    mode = "PAPER"
    if db_path and db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            # The vitals bar learns the schema before it speaks. No signals table? Find another voice.
            _sig_tables = [_r[0] for _r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            if "signals" in _sig_tables:
                row = conn.execute("SELECT ts FROM signals ORDER BY ts DESC LIMIT 1").fetchone()
            else:
                row = conn.execute("SELECT ts FROM events WHERE type LIKE 'signal.%' ORDER BY ts DESC LIMIT 1").fetchone()
            if row:
                try:
                    dt = _dt.datetime.fromisoformat(str(row["ts"]).replace("Z", ""))
                    age_s = (_dt.datetime.now(_dt.UTC).replace(tzinfo=None) - dt).total_seconds()
                    stale = age_s > 300
                    if age_s < 60:
                        last_signal_age = f"{int(age_s)}s"
                    elif age_s < 3600:
                        last_signal_age = f"{int(age_s / 60)}m"
                    else:
                        last_signal_age = f"{int(age_s / 3600)}h"
                except Exception:
                    pass
            try:
                tables_here = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                if "signals" in tables_here:
                    r = conn.execute("SELECT COUNT(DISTINCT producer_id) FROM signals WHERE ts > datetime('now','-1 hour')").fetchone()
                else:
                    # Fallback: count active sources from events table
                    r = conn.execute("SELECT COUNT(DISTINCT source) FROM events WHERE type LIKE 'signal.%' AND ts > datetime('now','-1 hour')").fetchone()
                producer_count = r[0] if r else 0
            except Exception:
                pass
            conn.close()
        except Exception:
            pass
    try:
        from engine.core.config import Config
        from engine.core.paths import config_dir as _config_dir

        _cfg_path = _config_dir() / "user.yaml"
        _cfg = Config.from_yaml(_cfg_path) if _cfg_path.exists() else Config.from_repo_defaults(None)
        if getattr(getattr(_cfg, "execution", None), "paper_trading", True) is False:
            mode = "LIVE"
    except Exception:
        pass
    return templates.TemplateResponse(
        request=request,
        name="partials/vitals_bar.html",
        context={
            "request": request,
            "last_signal_age": last_signal_age,
            "producer_count": producer_count,
            "mode": mode,
            "stale": stale,
        },
    )


@app.get("/partials/signal-detail/{signal_id}", response_class=HTMLResponse)
def signal_detail_partial(request: Request, signal_id: str) -> HTMLResponse:
    db_path = _get_brain_db()
    signal: dict = {}
    similar: list = []
    if db_path and db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM signals WHERE id=? LIMIT 1", (signal_id,)).fetchone()
            if row:
                signal = dict(row)
                pid = signal.get("producer_id")
                if pid:
                    rows = conn.execute("SELECT * FROM signals WHERE producer_id=? ORDER BY ts DESC LIMIT 5", (pid,)).fetchall()
                    similar = [dict(r) for r in rows]
            conn.close()
        except Exception:
            pass
    return templates.TemplateResponse(
        request=request,
        name="partials/signal_detail.html",
        context={
            "request": request,
            "signal": signal,
            "similar": similar,
        },
    )


@app.get("/partials/signal-feed", response_class=HTMLResponse)
def signal_feed_partial(request: Request) -> HTMLResponse:
    client = _api(request)
    res = client.get_signals(domain=None)
    signals = _map_signals(res.data)
    total = res.data.get("total") if (res.ok and isinstance(res.data, dict)) else 0

    return templates.TemplateResponse(
        request=request,
        name="partials/signal_feed.html",
        context={"request": request, "signals": signals[:30], "total_signals": total},
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
        request=request,
        name="partials/system_status_panel.html",
        context={
            "request": request,
            "cycle_age": cycle_age,
            "cycle_age_min": cycle_age_min,
            "producers_healthy": producers_healthy,
            "producers_total": producers_total,
            **_system_status_ctx(),
            "karma_pending": karma_pending,
        },
    )


@app.get("/partials/producers", response_class=HTMLResponse)
def producers_partial(request: Request) -> HTMLResponse:
    client = _api(request)
    prod_res = client.get_producers_status()
    producers_map = prod_res.data.get("producers") if (prod_res.ok and isinstance(prod_res.data, dict)) else {}

    # Collect configurable producer names for "Configure →" links
    _config_producer_names: set[str] = set()
    try:
        from engine.producers.registry import get_producer as _get_reg
        from engine.producers.registry import list_producers as _list_reg

        for pname in _list_reg():
            cls = _get_reg(pname)
            if getattr(cls, "configurable_fields", None):
                _config_producer_names.add(pname)
    except Exception:
        pass

    producers: list[dict[str, Any]] = []
    producers_healthy = 0
    if isinstance(producers_map, dict):
        for name, v in producers_map.items():
            if not isinstance(v, dict):
                continue
            healthy = v.get("healthy")
            consecutive_failures = int(v.get("consecutive_failures") or 0)
            last_error_raw = v.get("last_error")
            last_error = str(last_error_raw).strip() if last_error_raw not in (None, "") else None
            last_error_lc = last_error.lower() if last_error else ""
            no_source = "no_source_configured" in last_error_lc or "no source configured" in last_error_lc or "not configured" in last_error_lc
            quarantined_until_raw = v.get("quarantined_until")
            events_produced = int(v.get("events_produced") or v.get("event_count") or 0)

            last_run = "—"
            last_run_dt: datetime | None = None
            if isinstance(v.get("last_run_at"), str):
                try:
                    dt = datetime.fromisoformat(str(v["last_run_at"]).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=UTC)
                    last_run_dt = dt.astimezone(UTC)
                    last_run, _ = _age_str(last_run_dt)
                except Exception:
                    last_run = "—"

            is_stale = bool(last_run_dt and (datetime.now(tz=UTC) - last_run_dt).total_seconds() > 30 * 60)
            zero_events_warning = bool(last_run_dt and events_produced <= 0 and not last_error and consecutive_failures == 0)

            # Determine status: quarantined > stale > failing > degraded > healthy
            quarantined_until_fmt: str | None = None
            is_quarantined = False
            if quarantined_until_raw:
                try:
                    q_str = str(quarantined_until_raw).replace("Z", "+00:00")
                    q_dt = datetime.fromisoformat(q_str)
                    if q_dt.tzinfo is None:
                        q_dt = q_dt.replace(tzinfo=UTC)
                    if q_dt > datetime.now(tz=UTC):
                        is_quarantined = True
                        quarantined_until_fmt = q_dt.strftime("%H:%M UTC")
                except Exception:
                    pass

            if is_quarantined:
                status = "quarantined"
                health = "error"
            elif is_stale:
                status = "stale"
                health = "degraded"
            elif consecutive_failures > 4:
                status = "failing"
                health = "error"
            elif no_source or consecutive_failures > 0 or last_error or zero_events_warning:
                status = "degraded"
                health = "degraded"
            elif healthy is True or last_run_dt is not None:
                status = "healthy"
                health = "ok"
            elif healthy is False:
                status = "error"
                health = "error"
            else:
                status = "unknown"
                health = "degraded"

            if status == "healthy":
                producers_healthy += 1

            producers.append(
                {
                    "name": str(name),
                    "domain": v.get("domain") or "—",
                    "health": health,
                    "last_run": last_run,
                    "status": status,
                    "last_error": last_error,
                    "consecutive_failures": consecutive_failures,
                    "events_produced": events_produced,
                    "quarantined_until": quarantined_until_fmt,
                    "is_stale": is_stale,
                    "zero_events_warning": zero_events_warning,
                    "no_source": no_source,
                    "has_config": name in _config_producer_names,
                }
            )

    return templates.TemplateResponse(
        request=request,
        name="partials/producers_panel.html",
        context={
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
        request=request,
        name="partials/kill_switch_panel.html",
        context={
            "request": request,
            "kill_switch_level": level,
            "kill_switch_label": label,
            "kill_switch_last_change": kill_last_change,
        },
    )


@app.get("/partials/sentiment-map", response_class=HTMLResponse)
def sentiment_map_partial(request: Request) -> HTMLResponse:
    client = _api(request)
    sent_res = client.get_social_sentiment()
    status_res = client.get_social_status()

    sentiments = sent_res.data.get("items") if (sent_res.ok and isinstance(sent_res.data, dict)) else []
    status_data = status_res.data if (status_res.ok and isinstance(status_res.data, dict)) else {}

    sources_active = int(status_data.get("sources_configured", 0) or 0)
    signal_events_count = int(status_data.get("signal_events_count", 0) or 0)

    if sources_active == 0:
        src_res = client.get_social_sources()
        if src_res.ok and isinstance(src_res.data, dict):
            source_items = src_res.data.get("items", [])
            if isinstance(source_items, list):
                sources_active = len(source_items)

    return templates.TemplateResponse(
        request=request,
        name="partials/sentiment_map_panel.html",
        context={
            "request": request,
            "sentiment_age": "—" if sent_res.ok else "stale",
            "sources_active": sources_active,
            "signal_events_count": signal_events_count,
            "sentiments": sentiments if isinstance(sentiments, list) else [],
        },
    )


@app.get("/partials/social-alerts", response_class=HTMLResponse)
def social_alerts_partial(request: Request) -> HTMLResponse:
    client = _api(request)
    res = client.get_social_alerts()
    alerts = res.data.get("items") if (res.ok and isinstance(res.data, dict)) else []

    return templates.TemplateResponse(
        request=request,
        name="partials/social_alerts_panel.html",
        context={"request": request, "alerts": alerts if isinstance(alerts, list) else []},
    )


@app.get("/partials/curator-feed", response_class=HTMLResponse)
def curator_feed_partial(request: Request) -> HTMLResponse:
    client = _api(request)
    res = client.get_curator_feed()
    curator_signals = res.data.get("items") if (res.ok and isinstance(res.data, dict)) else []

    return templates.TemplateResponse(
        request=request,
        name="partials/curator_feed.html",
        context={"request": request, "curator_signals": curator_signals if isinstance(curator_signals, list) else []},
    )


@app.get("/partials/karma-intents", response_class=HTMLResponse)
def karma_intents_partial(request: Request) -> HTMLResponse:
    client = _api(request)
    res = client.get_karma_intents()
    intents = res.data.get("items") if (res.ok and isinstance(res.data, dict)) else []

    return templates.TemplateResponse(
        request=request,
        name="partials/karma_intents_panel.html",
        context={"request": request, "intents": intents if isinstance(intents, list) else []},
    )


@app.get("/partials/signal-history", response_class=HTMLResponse)
def signal_history_partial(request: Request, domain: str | None = None) -> HTMLResponse:
    client = _api(request)
    res = client.get_signals(domain=domain)
    signals = _map_signals(res.data)
    total = res.data.get("total") if (res.ok and isinstance(res.data, dict)) else 0

    return templates.TemplateResponse(
        request=request,
        name="partials/signal_history.html",
        context={"request": request, "signals": signals, "total_signals": total, "active_domain": domain},
    )


# ---- Social action partials (HTMX POST handlers) ----------------------


def _feedback(message: str, level: str = "info") -> dict[str, str]:
    return {"message": message, "level": level}


@app.post("/social/action/seed", response_class=HTMLResponse)
def social_action_seed(request: Request) -> HTMLResponse:
    client = _api(request)
    res = client.post_social_seed()

    if res.ok and isinstance(res.data, dict):
        count = int(res.data.get("count", 0) or 0)
        msg = str(res.data.get("message") or "Seed request completed")
        level = "success" if count > 0 else "warning"
        return _social_status_partial(request, feedback=_feedback(msg, level))

    return _social_status_partial(request, feedback=_feedback("Seed request failed — API unreachable", "error"))


@app.post("/social/action/reset-failures", response_class=HTMLResponse)
def social_action_reset(request: Request) -> HTMLResponse:
    client = _api(request)
    res = client.post_social_reset_failures()

    if res.ok and isinstance(res.data, dict):
        reset_count = int(res.data.get("producers_reset", 0) or 0)
        if reset_count > 0:
            msg = f"Reset failures for {reset_count} producer{'s' if reset_count != 1 else ''}."
            level = "success"
        else:
            msg = "No producer failures to reset."
            level = "warning"
        return _social_status_partial(request, feedback=_feedback(msg, level))

    return _social_status_partial(request, feedback=_feedback("Reset request failed — API unreachable", "error"))


@app.post("/social/action/run-now", response_class=HTMLResponse)
def social_action_run(request: Request) -> HTMLResponse:
    client = _api(request)
    res = client.post_social_run_now()

    if res.ok and isinstance(res.data, dict):
        msg = str(res.data.get("message") or "Run now request submitted")
        if bool(res.data.get("already_running", False)):
            level = "warning"
        else:
            level = "success" if bool(res.data.get("triggered", True)) else "warning"
        return _social_status_partial(request, feedback=_feedback(msg, level))

    return _social_status_partial(request, feedback=_feedback("Run now failed — API unreachable", "error"))


@app.post("/social/action/add-to-watchlist", response_class=HTMLResponse)
async def social_action_add_watchlist(request: Request) -> HTMLResponse:
    form = await request.form()
    symbol = str(form.get("symbol", "")).strip().upper()
    if not symbol:
        return _social_watchlist_partial(request, feedback=_feedback("Symbol is required", "error"))

    client = _api(request)
    res = client.post_social_add_watchlist(symbol)
    if res.ok and isinstance(res.data, dict):
        added = bool(res.data.get("added", False))
        msg = str(res.data.get("message") or (f"Added {symbol} to watchlist" if added else f"{symbol} is already on watchlist"))
        level = "success" if added else "warning"
        return _social_watchlist_partial(request, feedback=_feedback(msg, level))

    return _social_watchlist_partial(request, feedback=_feedback("Failed to add watchlist symbol — API unreachable", "error"))


@app.delete("/social/action/remove-from-watchlist/{symbol}", response_class=HTMLResponse)
def social_action_remove_watchlist(request: Request, symbol: str) -> HTMLResponse:
    client = _api(request)
    sym = symbol.strip().upper()
    if not sym:
        return _social_watchlist_partial(request, feedback=_feedback("Symbol is required", "error"))

    res = client.delete_social_watchlist(sym)
    if res.ok and isinstance(res.data, dict):
        removed = bool(res.data.get("removed", False))
        msg = str(res.data.get("message") or (f"Removed {sym} from watchlist" if removed else f"{sym} was not in watchlist"))
        level = "success" if removed else "warning"
        return _social_watchlist_partial(request, feedback=_feedback(msg, level))

    return _social_watchlist_partial(request, feedback=_feedback("Failed to remove watchlist symbol — API unreachable", "error"))


@app.post("/social/action/add-source", response_class=HTMLResponse)
async def social_action_add_source(request: Request) -> HTMLResponse:
    form = await request.form()
    name = str(form.get("name", "")).strip()
    src_type = str(form.get("type", "")).strip()
    value = str(form.get("value", "")).strip()

    if not name or not src_type or not value:
        return _social_sources_partial(request, feedback=_feedback("Name, type, and value are required", "error"))

    client = _api(request)
    res = client.post_social_add_source(name, src_type, value)
    if res.ok and isinstance(res.data, dict):
        added = bool(res.data.get("added", False))
        msg = str(res.data.get("message") or (f"Added source: {name}" if added else f"Source already exists: {name}"))
        level = "success" if added else "warning"
        return _social_sources_partial(request, feedback=_feedback(msg, level))

    return _social_sources_partial(request, feedback=_feedback("Failed to add source — API unreachable", "error"))


def _social_status_partial(request: Request, feedback: dict[str, str] | None = None) -> HTMLResponse:
    client = _api(request)
    status_res = client.get_social_status()
    status_data = status_res.data if (status_res.ok and isinstance(status_res.data, dict)) else {}

    pipeline_status = str(status_data.get("pipeline_status", "unknown"))
    pipeline_active = bool(status_data.get("pipeline_active", False))
    diagnosis = str(status_data.get("diagnosis", "Unable to reach social status API"))
    actions_available = status_data.get("actions_available", [])
    producer_health = status_data.get("producers", [])
    seeded = bool(status_data.get("seeded", False))
    watchlist_count = int(status_data.get("watchlist_count", 0) or 0)
    sources_configured = int(status_data.get("sources_configured", 0) or 0)
    signal_events_count = int(status_data.get("signal_events_count", 0) or 0)
    failing_producers = int(status_data.get("failing_producers", 0) or 0)

    pipeline_last_run = "never"
    newest_run: datetime | None = None
    for p in producer_health if isinstance(producer_health, list) else []:
        if not isinstance(p, dict) or not p.get("last_run_at"):
            continue
        try:
            dt = datetime.fromisoformat(str(p["last_run_at"]).replace("Z", "+00:00"))
            if newest_run is None or dt > newest_run:
                newest_run = dt
        except Exception:
            continue
    if newest_run is not None:
        pipeline_last_run, _ = _age_str(newest_run)

    signal_last_seen = "never"
    raw_last_signal = status_data.get("last_signal_at")
    if isinstance(raw_last_signal, str) and raw_last_signal:
        try:
            dt = datetime.fromisoformat(raw_last_signal.replace("Z", "+00:00"))
            signal_last_seen, _ = _age_str(dt)
        except Exception:
            signal_last_seen = raw_last_signal

    status_feedback = feedback
    if status_feedback is None and not status_res.ok:
        status_feedback = _feedback("Unable to refresh status from API", "error")

    return templates.TemplateResponse(
        request=request,
        name="partials/social_status_panel.html",
        context={
            "request": request,
            "pipeline_active": pipeline_active,
            "pipeline_status": pipeline_status,
            "pipeline_last_run": pipeline_last_run,
            "diagnosis": diagnosis,
            "actions_available": actions_available if isinstance(actions_available, list) else [],
            "producer_health": producer_health if isinstance(producer_health, list) else [],
            "seeded": seeded,
            "watchlist_count": watchlist_count,
            "sources_configured": sources_configured,
            "signal_events_count": signal_events_count,
            "failing_producers": failing_producers,
            "signal_last_seen": signal_last_seen,
            "status_feedback": status_feedback,
        },
    )


def _social_watchlist_partial(request: Request, feedback: dict[str, str] | None = None) -> HTMLResponse:
    client = _api(request)
    wl_res = client.get_social_watchlist()
    watchlist: list[dict[str, Any]] = []
    if wl_res.ok and isinstance(wl_res.data, dict):
        watchlist = wl_res.data.get("items", [])
    symbols = [str(w.get("symbol", "")) for w in watchlist if isinstance(w, dict)]

    status_feedback = feedback
    if status_feedback is None and not wl_res.ok:
        status_feedback = _feedback("Unable to refresh watchlist from API", "error")

    return templates.TemplateResponse(
        request=request,
        name="partials/social_watchlist_panel.html",
        context={
            "request": request,
            "watchlist": symbols,
            "watchlist_count": len(symbols),
            "status_feedback": status_feedback,
            "api_ok": wl_res.ok,
        },
    )


def _social_sources_partial(request: Request, feedback: dict[str, str] | None = None) -> HTMLResponse:
    client = _api(request)
    src_res = client.get_social_sources()
    sources: list[dict[str, Any]] = []
    if src_res.ok and isinstance(src_res.data, dict):
        sources = src_res.data.get("items", [])

    status_feedback = feedback
    if status_feedback is None and not src_res.ok:
        status_feedback = _feedback("Unable to refresh sources from API", "error")

    return templates.TemplateResponse(
        request=request,
        name="partials/social_sources_panel.html",
        context={
            "request": request,
            "sources": sources if isinstance(sources, list) else [],
            "status_feedback": status_feedback,
            "api_ok": src_res.ok,
        },
    )


@app.get("/partials/collector-health", response_class=HTMLResponse)
def collector_health_partial(request: Request) -> HTMLResponse:
    client = _api(request)
    res = client.get_collector_health()

    collectors: list[dict[str, Any]] = []
    summary: dict[str, int] = {}
    health_error: str | None = None
    if res.ok and isinstance(res.data, dict):
        collectors = res.data.get("collectors", [])
        summary = res.data.get("summary", {}) if isinstance(res.data.get("summary"), dict) else {}
    else:
        health_error = "Unable to reach collector health endpoint"

    return templates.TemplateResponse(
        request=request,
        name="partials/social_collector_health.html",
        context={
            "request": request,
            "collectors": collectors,
            "collector_summary": summary,
            "health_error": health_error,
        },
    )


@app.get("/partials/social-status", response_class=HTMLResponse)
def social_status_partial_get(request: Request) -> HTMLResponse:
    return _social_status_partial(request)


@app.get("/partials/social-watchlist", response_class=HTMLResponse)
def social_watchlist_partial_get(request: Request) -> HTMLResponse:
    return _social_watchlist_partial(request)


@app.get("/partials/social-sources", response_class=HTMLResponse)
def social_sources_partial_get(request: Request) -> HTMLResponse:
    return _social_sources_partial(request)


# ---- Dashboard version API endpoint -----------------------------------


@app.get("/api/dashboard/version")
def dashboard_version_endpoint() -> dict:
    """Return dashboard version info including git SHA."""
    import subprocess  # noqa: PLC0415

    git_sha: str | None = None
    with contextlib.suppress(Exception):
        git_sha = subprocess.check_output(  # noqa: S603, S607
            ["git", "rev-parse", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()

    return {
        "version": DASHBOARD_VERSION,
        "git_sha": git_sha,
        "changelog_url": "https://github.com/P-U-C/b1e55ed/blob/develop/dashboard/CHANGELOG.md",
    }


# ---- Optional pages backed by local DB --------------------------------

# These pages intentionally read from the local SQLite journal. They do not
# require the API layer to be reachable.
from dashboard.contributors import register as _register_contributors  # noqa: E402
from dashboard.identity import register as _register_identity  # noqa: E402
from dashboard.producers import register as _register_producers  # noqa: E402
from dashboard.routes.cockpit import register as _register_cockpit  # noqa: E402
from dashboard.routes.conviction import register as _register_conviction  # noqa: E402
from dashboard.webhooks import register as _register_webhooks  # noqa: E402

_register_cockpit(app, templates)
_register_conviction(app, templates)
_register_contributors(app, templates)
_register_identity(app, templates)
_register_webhooks(app, templates)
_register_producers(app, templates)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=5051)
