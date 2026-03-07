from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


def _repo_root() -> Path:
    import os

    override = os.environ.get("B1E55ED_REPO_ROOT")
    if override:
        return Path(override)
    from engine.core.paths import b1e55ed_dir

    return b1e55ed_dir()


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
class ProducerRow:
    name: str
    domain: str
    endpoint: str
    schedule: str
    last_run: str
    healthy: bool | None
    events_produced: int
    last_success: str
    consecutive_failures: int
    last_error: str | None
    quarantined_until: str | None
    status: str


def _producer_healthy(*, consecutive_failures: int, last_error: str | None) -> bool | None:
    if consecutive_failures == 0 and not last_error:
        return True
    if consecutive_failures > 0 or last_error:
        return False
    return None


def _list_producers(conn: sqlite3.Connection) -> list[ProducerRow]:
    cols = [str(r[1]) for r in conn.execute("PRAGMA table_info(producer_health)").fetchall()]
    has_endpoint = "endpoint" in cols

    has_quarantined = "quarantined_until" in cols

    base_cols = "name, domain, schedule, last_run_at, last_success_at, last_error, consecutive_failures, events_produced"
    if has_endpoint:
        base_cols = "name, domain, endpoint, schedule, last_run_at, last_success_at, last_error, consecutive_failures, events_produced"
    if has_quarantined:
        base_cols += ", quarantined_until"

    rows = conn.execute(f"SELECT {base_cols} FROM producer_health ORDER BY name ASC").fetchall()

    now = datetime.now(tz=UTC)
    out: list[ProducerRow] = []
    for r in rows:
        if has_endpoint:
            name = str(r[0] or "—")
            domain = str(r[1] or "—")
            endpoint = str(r[2] or "—")
            schedule = str(r[3] or "—")
            last_run_at = str(r[4]) if r[4] is not None else None
            last_success_at = str(r[5]) if r[5] is not None else None
            last_error = str(r[6]) if r[6] is not None else None
            consecutive_failures = int(r[7] or 0)
            events_produced = int(r[8] or 0)
            q_idx = 9
        else:
            name = str(r[0] or "—")
            domain = str(r[1] or "—")
            endpoint = "—"
            schedule = str(r[2] or "—")
            last_run_at = str(r[3]) if r[3] is not None else None
            last_success_at = str(r[4]) if r[4] is not None else None
            last_error = str(r[5]) if r[5] is not None else None
            consecutive_failures = int(r[6] or 0)
            events_produced = int(r[7] or 0)
            q_idx = 8

        quarantined_until_raw = str(r[q_idx]) if has_quarantined and r[q_idx] is not None else None

        # Determine quarantine display
        quarantined_until_fmt: str | None = None
        is_quarantined = False
        if quarantined_until_raw:
            q_dt = _parse_dt(quarantined_until_raw)
            if q_dt and q_dt > now:
                is_quarantined = True
                quarantined_until_fmt = q_dt.strftime("%H:%M UTC")

        # Triage predates software. Nightingale sorted the wounded the same way: healthy, degraded, failing.
        # Determine status
        if is_quarantined:
            status = "quarantined"
        elif consecutive_failures == 0:
            status = "healthy"
        elif consecutive_failures <= 4:
            status = "degraded"
        else:
            status = "failing"

        healthy = _producer_healthy(consecutive_failures=consecutive_failures, last_error=last_error)

        out.append(
            ProducerRow(
                name=name,
                domain=domain,
                endpoint=endpoint,
                schedule=schedule,
                last_run=_fmt_ts(last_run_at),
                healthy=healthy,
                events_produced=events_produced,
                last_success=_fmt_ts(last_success_at),
                consecutive_failures=consecutive_failures,
                last_error=last_error,
                quarantined_until=quarantined_until_fmt,
                status=status,
            )
        )

    return out


def _ensure_endpoint_column(conn: sqlite3.Connection) -> None:
    cols = [str(r[1]) for r in conn.execute("PRAGMA table_info(producer_health)").fetchall()]
    if "endpoint" in cols:
        return
    with conn:
        conn.execute("ALTER TABLE producer_health ADD COLUMN endpoint TEXT")


def _upsert_producer(conn: sqlite3.Connection, *, name: str, domain: str, endpoint: str, schedule: str) -> None:
    _ensure_endpoint_column(conn)
    now = datetime.now(tz=UTC).isoformat()

    existing = conn.execute("SELECT name FROM producer_health WHERE name = ?", (name,)).fetchone()
    with conn:
        if existing is None:
            conn.execute(
                """
                INSERT INTO producer_health (name, domain, endpoint, schedule, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, domain, endpoint, schedule, now),
            )
        else:
            conn.execute(
                """
                UPDATE producer_health
                SET domain = ?, endpoint = ?, schedule = ?, updated_at = ?
                WHERE name = ?
                """,
                (domain, endpoint, schedule, now, name),
            )


def register(app: FastAPI, templates: Jinja2Templates) -> None:
    domains = ["technical", "sentiment", "onchain", "macro", "social", "curator", "events", "tradfi"]

    @app.get("/producers", response_class=HTMLResponse)
    def producers_page(request: Request) -> HTMLResponse:
        conn = _connect_db()
        if conn is None:
            producers: list[ProducerRow] = []
        else:
            with conn:
                producers = _list_producers(conn)
            conn.close()

        return templates.TemplateResponse(
            "producers.html",
            {
                "request": request,
                "active_page": "producers",
                "kill_switch_level": 0,
                "regime": "transition",
                "producers": producers,
                "domains": domains,
                "form_result": None,
            },
        )

    @app.post("/producers/register", response_class=HTMLResponse)
    async def producers_register(request: Request) -> HTMLResponse:
        form = await request.form()
        name = str(form.get("name") or "").strip()
        domain = str(form.get("domain") or "").strip()
        endpoint = str(form.get("endpoint") or "").strip()
        schedule = str(form.get("schedule") or "*/15 * * * *").strip()

        conn = _connect_db()
        if conn is None:
            producers: list[ProducerRow] = []
            result = {"ok": False, "message": "Database not present"}
        else:
            with conn:
                try:
                    _upsert_producer(conn, name=name, domain=domain, endpoint=endpoint, schedule=schedule)
                    result = {"ok": True, "message": "Registered"}
                except Exception:
                    result = {"ok": False, "message": "Registration failed"}
                producers = _list_producers(conn)
            conn.close()

        return templates.TemplateResponse(
            "producers.html",
            {
                "request": request,
                "active_page": "producers",
                "kill_switch_level": 0,
                "regime": "transition",
                "producers": producers,
                "domains": domains,
                "form_result": result,
            },
        )
