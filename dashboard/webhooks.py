from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _db_path() -> Path:
    override = os.getenv("B1E55ED_DB_PATH")
    if override:
        return Path(override)
    return _repo_root() / "data" / "brain.db"


def _connect_db() -> sqlite3.Connection | None:
    path = _db_path()
    if not path.exists():
        return None
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    v = value
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _fmt_ts(value: str | None) -> str:
    dt = _parse_dt(value)
    if dt is None:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M")


@dataclass(frozen=True)
class WebhookRow:
    name: str
    url: str
    events: str
    created: str
    last_delivery: str
    status: str


def _list_webhooks(conn: sqlite3.Connection) -> list[WebhookRow]:
    rows = conn.execute(
        """
        SELECT id, url, event_globs, enabled, created_at
        FROM webhook_subscriptions
        ORDER BY id ASC
        """
    ).fetchall()

    out: list[WebhookRow] = []
    for r in rows:
        enabled = bool(int(r[3] or 0))
        out.append(
            WebhookRow(
                name=f"#{int(r[0])}",
                url=str(r[1] or "—"),
                events=str(r[2] or "—"),
                created=_fmt_ts(str(r[4]) if r[4] is not None else None),
                last_delivery="—",
                status="enabled" if enabled else "disabled",
            )
        )
    return out


def _recent_deliveries(conn: sqlite3.Connection, *, limit: int = 20) -> list[dict[str, Any]]:
    _ = (conn, limit)
    # Delivery journaling is not implemented in the engine yet.
    return []


def register(app: FastAPI, templates: Jinja2Templates) -> None:
    @app.get("/webhooks", response_class=HTMLResponse)
    def webhooks_page(request: Request) -> HTMLResponse:
        conn = _connect_db()
        if conn is None:
            webhooks: list[WebhookRow] = []
            deliveries: list[dict[str, Any]] = []
        else:
            with conn:
                webhooks = _list_webhooks(conn)
                deliveries = _recent_deliveries(conn)
            conn.close()

        return templates.TemplateResponse(
            "webhooks.html",
            {
                "request": request,
                "active_page": "webhooks",
                "kill_switch_level": 0,
                "regime": "transition",
                "webhooks": webhooks,
                "deliveries": deliveries,
            },
        )
