#!/usr/bin/env python3
"""API + Dashboard smoke test suite with TestClient and temporary database.

Hits every dashboard page (14 routes), every HTMX partial (22 endpoints),
and every API endpoint (27+ routes). Validates 200 responses and JSON schemas.
Bootstraps its own temporary database — no running servers needed.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

RESULTS_PATH = "/tmp/api_smoke_results.json"

AUTH_TOKEN = "test-smoke-token-12345"


@dataclass
class Result:
    category: str
    endpoint: str
    method: str
    status: int = 0
    ok: bool = False
    response_ms: float = 0.0
    content_type: str = ""
    errors: list[str] = field(default_factory=list)
    skipped: bool = False


DASHBOARD_PAGES = [
    "/",
    "/home",
    "/cockpit",
    "/positions",
    "/signals",
    "/conviction",
    "/forecasts",
    "/social",
    "/artifacts",
    "/performance",
    "/system",
    "/settings",
    "/config",
    "/treasury",
]

HTMX_PARTIALS = [
    "/partials/kill-dot",
    "/partials/regime-pill",
    "/partials/regime-banner",
    "/partials/positions",
    "/partials/vitals-bar",
    "/partials/signal-feed",
    "/partials/system-status",
    "/partials/producers",
    "/partials/kill-switch",
    "/partials/sentiment-map",
    "/partials/social-alerts",
    "/partials/curator-feed",
    "/partials/karma-intents",
    "/partials/signal-history",
    "/partials/forecasts-table",
    "/partials/discretionary-signals",
    "/partials/cockpit-content",
    "/partials/conviction",
    "/partials/conviction-history",
    "/partials/social-status",
    "/partials/social-watchlist",
    "/partials/social-sources",
]

DASHBOARD_API_ROUTES = ["/api/market-ticker", "/api/dashboard/version"]

API_ROUTES: list[tuple[str, str, set[str] | None]] = [
    ("GET", "/api/v1/health", None),
    ("GET", "/api/v1/metrics", None),
    ("GET", "/api/v1/brain/status", None),
    ("GET", "/api/v1/kill-switch/status", None),
    ("GET", "/api/v1/signals", {"total", "items"}),
    ("GET", "/api/v1/positions", None),
    ("GET", "/api/v1/producers/", None),
    ("GET", "/api/v1/producers/status", None),
    ("GET", "/api/v1/producers/capabilities", None),
    ("GET", "/api/v1/contributors/", None),
    ("GET", "/api/v1/contributors/leaderboard", None),
    ("GET", "/api/v1/contributors/attestations", None),
    ("GET", "/api/v1/regime", None),
    ("GET", "/api/v1/config", None),
    ("GET", "/api/v1/treasury", None),
    ("GET", "/api/v1/karma/intents", None),
    ("GET", "/api/v1/karma/receipts", None),
    ("GET", "/api/v1/social/status", None),
    ("GET", "/api/v1/social/sentiment", None),
    ("GET", "/api/v1/social/alerts", None),
    ("GET", "/api/v1/social/narratives", None),
    ("GET", "/api/v1/social/sources", None),
    ("GET", "/api/v1/social/curator-feed", None),
    ("GET", "/api/v1/social/watchlist", None),
    ("GET", "/api/v1/artifacts/", None),
    ("GET", "/api/v1/cockpit/state", None),
    ("GET", "/api/v1/mcp/status", None),
]


def _setup_temp_env(tmp_dir: Path) -> None:
    """Bootstrap a temporary database using the real Database class for full schema."""
    os.environ["B1E55ED_DATA_DIR"] = str(tmp_dir)
    os.environ["B1E55ED_API__AUTH_TOKEN"] = AUTH_TOKEN
    os.environ["B1E55ED_DASHBOARD__AUTH_TOKEN"] = AUTH_TOKEN
    os.environ.setdefault("B1E55ED_REPO_ROOT", str(REPO_ROOT))

    from engine.core.database import Database

    db = Database(tmp_dir / "brain.db")

    # Seed a signal event for the test
    db.execute(
        "INSERT OR IGNORE INTO events (id, type, ts, payload, source, hash, prev_hash, observed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(uuid.uuid4()),
            "SIGNAL_TA_V1",
            "2026-03-10T12:00:00Z",
            json.dumps({"symbol": "BTC", "rsi_14": 45.2, "direction": "+", "score": 6.5}),
            "technical-analysis",
            "abc123",
            None,
            "2026-03-10T12:00:00Z",
        ),
    )
    db.close()


def run_smoke_tests() -> list[Result]:
    tmp = Path(tempfile.mkdtemp(prefix="b1e55ed_smoke_"))
    _setup_temp_env(tmp)

    from fastapi.testclient import TestClient

    results: list[Result] = []

    def _hit(client, category, method, route, headers=None, expected_keys=None):
        r = Result(category=category, endpoint=route, method=method)
        t0 = time.perf_counter()
        try:
            resp = client.get(route, headers=headers) if method == "GET" else client.post(route, headers=headers, json={})
            r.status = resp.status_code
            r.ok = resp.status_code == 200
            r.content_type = resp.headers.get("content-type", "")
            r.response_ms = (time.perf_counter() - t0) * 1000
            if r.ok and expected_keys and "json" in r.content_type:
                data = resp.json()
                if isinstance(data, dict):
                    missing = expected_keys - set(data.keys())
                    if missing:
                        r.errors.append(f"Missing keys: {missing}")
                        r.ok = False
            if not r.ok:
                r.errors.append(f"HTTP {resp.status_code}")
        except Exception as e:
            r.errors.append(str(e)[:100])
            r.response_ms = (time.perf_counter() - t0) * 1000
        results.append(r)

    # ── Dashboard app ──
    from dashboard.app import app as dash_app

    dash_client = TestClient(dash_app, raise_server_exceptions=False)

    for route in DASHBOARD_PAGES:
        _hit(dash_client, "Dashboard Page", "GET", route)
    for route in HTMX_PARTIALS:
        _hit(dash_client, "HTMX Partial", "GET", route)
    for route in DASHBOARD_API_ROUTES:
        _hit(dash_client, "Dashboard API", "GET", route)

    # ── API app ──
    from api.main import create_app

    api_app = create_app()
    api_client = TestClient(api_app, raise_server_exceptions=False)
    auth = {"Authorization": f"Bearer {AUTH_TOKEN}"}

    for method, route, keys in API_ROUTES:
        _hit(api_client, "API Route", method, route, headers=auth, expected_keys=keys)

    return results


def print_results(results: list[Result]) -> None:
    passed = sum(1 for r in results if r.ok)
    failed = sum(1 for r in results if not r.ok and not r.skipped)
    skipped = sum(1 for r in results if r.skipped)
    total = len(results)

    print()
    print("=" * 95)
    print("  b1e55ed Smoke Test Suite - Dashboard + API Route Coverage")
    print("=" * 95)
    print()
    print(f"  {'#':<4} {'Category':<18} {'Method':<6} {'Route':<42} {'Status':<6} {'Time':>8}  {'Result'}")
    print(f"  {'_' * 4} {'_' * 18} {'_' * 6} {'_' * 42} {'_' * 6} {'_' * 8}  {'_' * 6}")

    for i, r in enumerate(results, 1):
        icon = "PASS" if r.ok else ("SKIP" if r.skipped else "FAIL")
        ms = f"{r.response_ms:.1f}ms"
        print(f"  {i:<4} {r.category:<18} {r.method:<6} {r.endpoint:<42} {r.status:<6} {ms:>8}  {icon}")
        if r.errors and not r.ok:
            print(f"       > {r.errors[0][:70]}")

    print()
    print("=" * 95)
    print(f"  Total: {total} | Pass: {passed} | Fail: {failed} | Skip: {skipped}")
    print(f"  Coverage: {passed}/{total} routes ({100 * passed / total:.0f}%)")
    print("=" * 95)

    with open(RESULTS_PATH, "w") as f:
        json.dump([asdict(r) for r in results], f, indent=2)
    print(f"\n  Results saved to {RESULTS_PATH}")


if __name__ == "__main__":
    results = run_smoke_tests()
    print_results(results)
    sys.exit(0 if all(r.ok or r.skipped for r in results) else 1)
