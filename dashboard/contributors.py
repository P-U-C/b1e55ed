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


def _leaderboard(conn: sqlite3.Connection, *, limit: int = 25) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
          c.id AS contributor_id,
          c.name AS name,
          c.role AS role,
          COUNT(cs.id) AS signals,
          SUM(CASE WHEN cs.accepted = 1 THEN 1 ELSE 0 END) AS accepted,
          SUM(CASE WHEN cs.profitable = 1 THEN 1 ELSE 0 END) AS hits,
          MAX(cs.created_at) AS last_active,
          COALESCE(SUM(COALESCE(cs.signal_score, 0.0)), 0.0) AS score
        FROM contributors c
        LEFT JOIN contributor_signals cs ON cs.contributor_id = c.id
        GROUP BY c.id
        ORDER BY score DESC, signals DESC, c.name ASC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()

    out: list[dict[str, Any]] = []
    for idx, r in enumerate(rows, start=1):
        signals = int(r["signals"] or 0)
        accepted = int(r["accepted"] or 0)
        hits = int(r["hits"] or 0)
        hit_rate = (hits / accepted) if accepted > 0 else None

        out.append(
            {
                "rank": idx,
                "name": str(r["name"] or "—"),
                "role": str(r["role"] or "—"),
                "score": float(r["score"] or 0.0),
                "signals": signals,
                "hit_rate": hit_rate,
                "streak": "—",
                "last_active": _fmt_ts(r["last_active"]),
            }
        )

    return out


def _recent_activity(conn: sqlite3.Connection, *, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
          cs.created_at AS created_at,
          c.name AS contributor,
          cs.signal_asset AS asset,
          cs.signal_direction AS direction,
          cs.signal_score AS score,
          cs.accepted AS accepted
        FROM contributor_signals cs
        JOIN contributors c ON c.id = cs.contributor_id
        ORDER BY cs.created_at DESC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()

    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "time": _fmt_ts(r["created_at"]),
                "contributor": str(r["contributor"] or "—"),
                "asset": str(r["asset"] or "—"),
                "direction": str(r["direction"] or "—"),
                "score": float(r["score"] or 0.0),
                "accepted": bool(int(r["accepted"] or 0)),
            }
        )

    return out


@dataclass(frozen=True)
class ContributorStats:
    total_contributors: int
    total_signals: int
    avg_hit_rate: float | None
    active_today: int


def _stats(conn: sqlite3.Connection) -> ContributorStats:
    total_contributors = conn.execute("SELECT COUNT(*) FROM contributors").fetchone()[0]
    total_signals = conn.execute("SELECT COUNT(*) FROM contributor_signals").fetchone()[0]

    hr_row = conn.execute(
        """
        SELECT
          SUM(CASE WHEN profitable = 1 THEN 1 ELSE 0 END) AS hits,
          SUM(CASE WHEN accepted = 1 THEN 1 ELSE 0 END) AS accepted
        FROM contributor_signals
        """
    ).fetchone()

    hits = int(hr_row[0] or 0)
    accepted = int(hr_row[1] or 0)
    avg_hit_rate = (hits / accepted) if accepted > 0 else None

    today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    active_today = conn.execute(
        """
        SELECT COUNT(DISTINCT contributor_id)
        FROM contributor_signals
        WHERE date(created_at) = ?
        """,
        (today,),
    ).fetchone()[0]

    return ContributorStats(
        total_contributors=int(total_contributors or 0),
        total_signals=int(total_signals or 0),
        avg_hit_rate=avg_hit_rate,
        active_today=int(active_today or 0),
    )


def register(app: FastAPI, templates: Jinja2Templates) -> None:
    @app.get("/contributors", response_class=HTMLResponse)
    def contributors_page(request: Request) -> HTMLResponse:
        conn = _connect_db()
        if conn is None:
            leaderboard: list[dict[str, Any]] = []
            activity: list[dict[str, Any]] = []
            stats = ContributorStats(0, 0, None, 0)
        else:
            with conn:
                leaderboard = _leaderboard(conn)
                activity = _recent_activity(conn)
                stats = _stats(conn)
            conn.close()

        return templates.TemplateResponse(
            "contributors.html",
            {
                "request": request,
                "active_page": "contributors",
                "kill_switch_level": 0,
                "regime": "transition",
                "leaderboard": leaderboard,
                "recent_activity": activity,
                "stats": stats,
            },
        )
