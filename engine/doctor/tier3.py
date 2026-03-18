"""engine.doctor.tier3 — Live checks (requires running API/DB).

Checks:
- API health endpoint responds
- Auth token works (GET /api/v1/brain/status)
- Dashboard renders (HTTP GET localhost:5051 returns 200)
- Kill switch state from live API
- Recent events in production DB — when was last brain cycle?
- Producer health from producer_health table — how many degraded?
- Trade intent vs orders gap (are intents becoming trades?)
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from engine.doctor.tier0 import CheckResult


def _http_get(url: str, *, timeout: float = 5.0, headers: dict | None = None) -> tuple[int, str]:
    """Minimal HTTP GET without requiring httpx at import time."""
    import httpx

    try:
        r = httpx.get(url, timeout=timeout, headers=headers or {}, follow_redirects=True)
        return r.status_code, r.text[:2000]
    except Exception as e:
        return 0, str(e)


def check_api_health(api_base: str) -> CheckResult:
    """API /health endpoint responds with 200."""
    status, body = _http_get(f"{api_base}/health")
    if status == 200:
        return CheckResult("api_health", "pass", f"API health responds (HTTP {status})")
    if status > 0:
        return CheckResult("api_health", "warn", f"API returned HTTP {status}: {body[:200]}")
    return CheckResult(
        "api_health",
        "fail",
        f"API unreachable: {body[:200]}",
        remediation="Run: b1e55ed start",
    )


def check_api_auth(api_base: str, auth_token: str | None) -> CheckResult:
    """Auth token works against /api/v1/brain/status."""
    if not auth_token:
        return CheckResult("api_auth", "warn", "No auth token provided (pass --auth-token to test)")

    headers = {"Authorization": f"Bearer {auth_token}"}
    status, body = _http_get(f"{api_base}/api/v1/brain/status", headers=headers)
    if status == 200:
        return CheckResult("api_auth", "pass", "Auth token accepted (brain/status 200)")
    if status in (401, 403):
        return CheckResult(
            "api_auth",
            "fail",
            f"Auth rejected (HTTP {status})",
            remediation="Check auth_token in config/user.yaml",
        )
    return CheckResult("api_auth", "warn", f"Auth check returned HTTP {status}: {body[:200]}")


def check_dashboard(dash_base: str) -> CheckResult:
    """Dashboard responds with 200."""
    status, body = _http_get(dash_base)
    if status == 200:
        return CheckResult("dashboard", "pass", f"Dashboard responds (HTTP {status})")
    if status > 0:
        return CheckResult("dashboard", "warn", f"Dashboard returned HTTP {status}")
    return CheckResult(
        "dashboard",
        "fail",
        f"Dashboard unreachable: {body[:200]}",
        remediation="Run: b1e55ed start",
    )


def check_kill_switch_live(db_path: Path | None = None) -> CheckResult:
    """Kill switch state from production DB."""
    try:
        import json

        from engine.core.database import Database
        from engine.core.events import EventType
        from engine.core.paths import data_dir

        path = db_path or (data_dir() / "brain.db")
        if not path.exists():
            return CheckResult("kill_switch_live", "warn", "DB not found for kill switch check")

        db = Database(path)
        try:
            row = db.fetchone(
                "SELECT payload FROM events WHERE type = ? ORDER BY ts DESC LIMIT 1",
                (str(EventType.KILL_SWITCH_V1),),
            )
            if not row:
                return CheckResult("kill_switch_live", "pass", "Kill switch: L0 (safe, no events)")
            payload = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            level = int(payload.get("level", 0))
            reason = str(payload.get("reason", ""))
            if level == 0:
                return CheckResult("kill_switch_live", "pass", "Kill switch: L0 (safe)")
            return CheckResult(
                "kill_switch_live",
                "warn" if level < 3 else "fail",
                f"Kill switch: L{level} — {reason}",
                remediation="Run: b1e55ed kill-switch set 0",
            )
        finally:
            db.close()
    except Exception as e:
        return CheckResult("kill_switch_live", "warn", f"Kill switch check error: {e}")


def check_last_brain_cycle(db_path: Path | None = None) -> CheckResult:
    """How long since the last brain cycle?"""
    try:
        from engine.core.database import Database
        from engine.core.events import EventType
        from engine.core.paths import data_dir

        path = db_path or (data_dir() / "brain.db")
        if not path.exists():
            return CheckResult("last_brain_cycle", "warn", "DB not found")

        db = Database(path)
        try:
            row = db.fetchone(
                "SELECT ts FROM events WHERE type = ? ORDER BY ts DESC LIMIT 1",
                (str(EventType.BRAIN_CYCLE_V1),),
            )

            if not row:
                return CheckResult("last_brain_cycle", "warn", "No brain cycle events found")

            last_ts = str(row[0])
            try:
                from engine.core.time import parse_dt

                dt = parse_dt(last_ts)
                age = datetime.now(tz=UTC) - dt
                age_hours = age.total_seconds() / 3600

                if age_hours < 1:
                    return CheckResult("last_brain_cycle", "pass", f"Last cycle: {last_ts} ({age_hours:.1f}h ago)")
                if age_hours < 6:
                    return CheckResult("last_brain_cycle", "warn", f"Last cycle: {last_ts} ({age_hours:.1f}h ago — stale)")
                return CheckResult(
                    "last_brain_cycle",
                    "fail",
                    f"Last cycle: {last_ts} ({age_hours:.1f}h ago — very stale)",
                    remediation="Run: b1e55ed brain",
                )
            except Exception:
                return CheckResult("last_brain_cycle", "pass", f"Last cycle: {last_ts}")
        finally:
            db.close()
    except Exception as e:
        return CheckResult("last_brain_cycle", "warn", f"Brain cycle check error: {e}")


def check_producer_health(db_path: Path | None = None) -> CheckResult:
    """Producer health from producer_health table."""
    try:
        from engine.core.database import Database
        from engine.core.paths import data_dir

        path = db_path or (data_dir() / "brain.db")
        if not path.exists():
            return CheckResult("producer_health", "warn", "DB not found")

        db = Database(path)
        try:
            rows = db.fetchall("SELECT name, consecutive_failures, quarantined_until FROM producer_health")
            total = len(rows)
            if total == 0:
                return CheckResult("producer_health", "warn", "No producers registered")

            degraded = sum(1 for r in rows if int(r[1] or 0) > 0)
            quarantined = sum(1 for r in rows if r[2] is not None)

            if degraded == 0:
                return CheckResult("producer_health", "pass", f"All {total} producers healthy")
            return CheckResult(
                "producer_health",
                "warn" if degraded < total else "fail",
                f"{degraded}/{total} producers degraded, {quarantined} quarantined",
            )
        finally:
            db.close()
    except Exception as e:
        return CheckResult("producer_health", "warn", f"Producer health check error: {e}")


def check_intent_to_order(db_path: Path | None = None) -> CheckResult:
    """Trade intent vs orders gap — are intents becoming trades?"""
    try:
        from engine.core.database import Database
        from engine.core.events import EventType
        from engine.core.paths import data_dir

        path = db_path or (data_dir() / "brain.db")
        if not path.exists():
            return CheckResult("intent_to_order", "warn", "DB not found")

        db = Database(path)
        try:
            intent_row = db.fetchone(
                "SELECT COUNT(*) FROM events WHERE type = ?",
                (str(EventType.TRADE_INTENT_V1),),
            )
            order_row = db.fetchone("SELECT COUNT(*) FROM orders")

            intents = int(intent_row[0]) if intent_row else 0
            orders = int(order_row[0]) if order_row else 0

            if intents == 0:
                return CheckResult("intent_to_order", "warn", "No trade intents recorded yet")

            fill_rate = orders / intents if intents > 0 else 0.0
            if fill_rate >= 0.5:
                return CheckResult("intent_to_order", "pass", f"{orders}/{intents} intents filled ({fill_rate:.0%})")
            return CheckResult(
                "intent_to_order",
                "warn",
                f"Low fill rate: {orders}/{intents} ({fill_rate:.0%})",
            )
        finally:
            db.close()
    except Exception as e:
        return CheckResult("intent_to_order", "warn", f"Intent/order check error: {e}")


def run_tier3(
    *,
    api_port: int = 5050,
    dashboard_port: int = 5051,
    api_host: str = "127.0.0.1",
    auth_token: str | None = None,
    db_path: Path | None = None,
) -> list[CheckResult]:
    """Run all Tier 3 live checks."""
    api_base = f"http://{api_host}:{api_port}"
    dash_base = f"http://{api_host}:{dashboard_port}"

    return [
        check_api_health(api_base),
        check_api_auth(api_base, auth_token),
        check_dashboard(dash_base),
        check_kill_switch_live(db_path),
        check_last_brain_cycle(db_path),
        check_producer_health(db_path),
        check_intent_to_order(db_path),
    ]
