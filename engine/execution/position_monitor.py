"""engine.execution.position_monitor

Standalone position monitor for paper trading Phase 0.

Responsibilities:
1. Evaluate stop_loss and take_profit for every open position each run.
2. Time-based stop: close any paper position open > 72 hours that is also
   losing > 5% (prevents stale positions blocking the trade count).
3. Fetch mark prices from Binance (same logic as the dashboard / orchestrator).
4. Call PnLTracker.close_position when a stop/target is triggered.
5. Emit a clear audit event for every auto-close.

This module is intentionally free of orchestrator.py to satisfy the constraint
that orchestrator.py must not be modified.  The daemon wires this as a dedicated
``position-monitor`` scheduler.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType

_log = logging.getLogger("b1e55ed.position_monitor")

# ---------------------------------------------------------------------------
# Time-based stop constants
# ---------------------------------------------------------------------------

PAPER_TIME_STOP_HOURS: float = 72.0
PAPER_TIME_STOP_LOSS_PCT: float = 0.05  # 5 %


# ---------------------------------------------------------------------------
# Price fetching (mirrors orchestrator._resolve_mid_price)
# ---------------------------------------------------------------------------


def _fetch_price_from_db(db: Database, symbol: str) -> float | None:
    """Query the most recent PRICE_V1 event for *symbol*."""
    try:
        row = db.fetchone(
            """
            SELECT payload FROM events
            WHERE type IN ('signal.price_ws.v1', 'PRICE_V1')
              AND json_extract(payload, '$.symbol') = ?
            ORDER BY ts DESC LIMIT 1
            """,
            (symbol.upper(),),
        )
        if row is not None:
            payload = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            for key in ("price", "close", "mid"):
                val = payload.get(key)
                if val is not None:
                    price = float(val)
                    if price > 0:
                        return price
    except Exception:
        _log.debug("DB price lookup failed for %s", symbol, exc_info=True)
    return None


def _fetch_price_from_binance(symbol: str) -> float | None:
    """Fallback: Binance public ticker API."""
    try:
        ticker_symbol = f"{symbol.upper()}USDT"
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={ticker_symbol}"
        req = urllib.request.Request(url, headers={"User-Agent": "b1e55ed/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            price = float(data.get("price", 0))
            if price > 0:
                return price
    except Exception:
        _log.debug("Binance price lookup failed for %s", symbol, exc_info=True)
    return None


def resolve_mark_price(db: Database, symbol: str) -> float | None:
    """Return mark price for *symbol*: DB first, Binance fallback."""
    price = _fetch_price_from_db(db, symbol)
    if price is not None:
        return price
    price = _fetch_price_from_binance(symbol)
    if price is not None:
        return price
    _log.warning("No mark price available for %s — skipping", symbol)
    return None


# ---------------------------------------------------------------------------
# Core monitor logic
# ---------------------------------------------------------------------------


def monitor_positions(db: Database, config: Config) -> dict:
    """Evaluate all open positions and close those that hit a stop/target/time-stop.

    Returns a summary dict::

        {"evaluated": N, "closed_stop": N, "closed_target": N,
         "closed_time_stop": N, "errors": N}
    """
    from engine.execution.pnl import PnLTracker

    pnl = PnLTracker(db, config)
    # Phase 0: treat auto_paper_trade=True as paper mode for time-based stop
    is_paper = str(getattr(getattr(config, "execution", None), "mode", "paper")) == "paper"
    if not is_paper:
        is_paper = bool(getattr(getattr(config, "brain", None), "auto_paper_trade", True))

    stats: dict = {
        "evaluated": 0,
        "closed_stop": 0,
        "closed_target": 0,
        "closed_time_stop": 0,
        "errors": 0,
    }

    rows = db.fetchall("SELECT id, asset, direction, entry_price, stop_loss, take_profit, opened_at FROM positions WHERE status = 'open'")

    now = datetime.now(tz=UTC)

    for row in rows:
        pos_id = str(row[0])
        asset = str(row[1]).upper()
        direction = str(row[2]).lower()
        entry_price = float(row[3]) if row[3] is not None else 0.0
        stop_loss = float(row[4]) if row[4] is not None else None
        take_profit = float(row[5]) if row[5] is not None else None
        opened_at_raw = str(row[6]) if row[6] else None

        stats["evaluated"] += 1

        mark = resolve_mark_price(db, asset)
        if mark is None:
            continue

        close_reason = None

        # --- stop / take-profit -------------------------------------------
        if direction == "long":
            if stop_loss is not None and mark <= stop_loss:
                close_reason = "stop_loss"
            elif take_profit is not None and mark >= take_profit:
                close_reason = "take_profit"
        elif direction == "short":
            # For shorts: stop is ABOVE entry, take-profit is BELOW entry.
            if stop_loss is not None and mark >= stop_loss:
                close_reason = "stop_loss"
            elif take_profit is not None and mark <= take_profit:
                close_reason = "take_profit"

        # --- time-based stop (paper mode only) ----------------------------
        if close_reason is None and is_paper and opened_at_raw and entry_price > 0:
            try:
                opened_at = datetime.fromisoformat(opened_at_raw)
                if opened_at.tzinfo is None:
                    opened_at = opened_at.replace(tzinfo=UTC)
                age_hours = (now - opened_at).total_seconds() / 3600.0

                if age_hours >= PAPER_TIME_STOP_HOURS:
                    if direction == "long":
                        loss_pct = (entry_price - mark) / entry_price
                    else:  # short
                        loss_pct = (mark - entry_price) / entry_price

                    if loss_pct >= PAPER_TIME_STOP_LOSS_PCT:
                        close_reason = "time_stop"
                        _log.info(
                            "time-stop triggered: position %s %s %s open %.1fh loss=%.2f%% entry=%.4f mark=%.4f",
                            pos_id,
                            direction,
                            asset,
                            age_hours,
                            loss_pct * 100,
                            entry_price,
                            mark,
                        )
            except Exception:
                _log.debug("time-stop calculation failed for %s", pos_id, exc_info=True)

        if close_reason:
            try:
                realized = pnl.close_position(position_id=pos_id, exit_price=mark, reason=close_reason)
                _log.info(
                    "position-monitor: closed %s (%s %s) at %.4f reason=%s realized_pnl=%.2f",
                    pos_id,
                    direction,
                    asset,
                    mark,
                    close_reason,
                    realized,
                )
                # Emit a structured audit event so the event ledger is complete.
                db.append_event(
                    event_type=EventType.AUDIT_V1,
                    payload={
                        "reason": f"position_monitor_{close_reason}",
                        "position_id": pos_id,
                        "asset": asset,
                        "direction": direction,
                        "mark_price": mark,
                        "entry_price": entry_price,
                        "realized_pnl": realized,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                    },
                    source="execution.position_monitor",
                )
                if close_reason == "stop_loss":
                    stats["closed_stop"] += 1
                elif close_reason == "take_profit":
                    stats["closed_target"] += 1
                else:
                    stats["closed_time_stop"] += 1
            except Exception:
                _log.warning(
                    "position-monitor: close failed for %s reason=%s",
                    pos_id,
                    close_reason,
                    exc_info=True,
                )
                stats["errors"] += 1

    return stats
