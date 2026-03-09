#!/usr/bin/env python3
"""API smoke test — hits every endpoint, validates responses, saves results."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field

API_URL = os.environ.get("API_URL", "http://127.0.0.1:5050")
API_TOKEN = os.environ.get("API_TOKEN", "d3FlLSCvNcxEGDexTReZmdJfP7JIwnB0OtoTrsklCYE")
RESULTS_PATH = "/tmp/api_smoke_results.json"


@dataclass
class Result:
    endpoint: str
    method: str
    status: int = 0
    ok: bool = False
    response_ms: float = 0.0
    content_type: str = ""
    body_preview: str = ""
    errors: list[str] = field(default_factory=list)


def hit(method: str, path: str, data: bytes | None = None, expect_json: bool = True) -> Result:
    url = f"{API_URL}{path}"
    r = Result(endpoint=path, method=method)
    t0 = time.monotonic()
    try:
        req = urllib.request.Request(url, method=method, data=data)
        if data:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=15) as resp:
            r.status = resp.status
            r.content_type = resp.headers.get("Content-Type", "")
            body = resp.read(4096).decode("utf-8", errors="replace")
            r.body_preview = body[:200]
    except urllib.error.HTTPError as e:
        r.status = e.code
        body = e.read(2048).decode("utf-8", errors="replace")
        r.body_preview = body[:200]
        r.errors.append(f"HTTP {e.code}: {body[:100]}")
    except Exception as e:
        r.errors.append(str(e))
    r.response_ms = round((time.monotonic() - t0) * 1000, 1)

    if r.status == 0:
        r.errors.append("No response (connection failed)")
    elif r.status >= 500:
        r.errors.append(f"Server error: {r.status}")

    if expect_json and r.status == 200:
        try:
            json.loads(r.body_preview if len(r.body_preview) < 4096 else "{}")
        except json.JSONDecodeError:
            if "application/json" in r.content_type:
                r.errors.append("Response claims JSON but failed to parse")

    r.ok = r.status in (200, 201) and len(r.errors) == 0
    return r


def main() -> int:
    results: list[Result] = []

    # ── Health / Meta ──
    results.append(hit("GET", "/api/v1/health"))
    results.append(hit("GET", "/api/v1/metrics", expect_json=False))

    # ── Brain ──
    results.append(hit("GET", "/api/v1/brain/status"))

    # ── Kill Switch ──
    results.append(hit("GET", "/api/v1/kill-switch/status"))

    # ── Signals ──
    results.append(hit("GET", "/api/v1/signals"))

    # ── Positions ──
    results.append(hit("GET", "/api/v1/positions"))

    # ── Producers ──
    results.append(hit("GET", "/api/v1/producers/"))
    results.append(hit("GET", "/api/v1/producers/status"))
    results.append(hit("GET", "/api/v1/producers/capabilities"))

    # ── Contributors ──
    results.append(hit("GET", "/api/v1/contributors/"))
    results.append(hit("GET", "/api/v1/contributors/leaderboard"))
    results.append(hit("GET", "/api/v1/contributors/attestations"))

    # ── Regime ──
    results.append(hit("GET", "/api/v1/regime"))

    # ── Config ──
    results.append(hit("GET", "/api/v1/config"))

    # ── Karma / Treasury ──
    results.append(hit("GET", "/api/v1/treasury"))
    results.append(hit("GET", "/api/v1/karma/intents"))
    results.append(hit("GET", "/api/v1/karma/receipts"))

    # ── Social ──
    results.append(hit("GET", "/api/v1/social/status"))
    results.append(hit("GET", "/api/v1/social/sentiment"))
    results.append(hit("GET", "/api/v1/social/alerts"))
    results.append(hit("GET", "/api/v1/social/narratives"))
    results.append(hit("GET", "/api/v1/social/sources"))
    results.append(hit("GET", "/api/v1/social/curator-feed"))
    results.append(hit("GET", "/api/v1/social/watchlist"))

    # ── Artifacts ──
    results.append(hit("GET", "/api/v1/artifacts/"))

    # ── Cockpit ──
    results.append(hit("GET", "/api/v1/cockpit/state"))

    # ── Oracle ──
    results.append(hit("GET", "/api/v1/oracle/"))

    # ── Benchmarks (POST-only, send minimal body) ──
    results.append(hit("POST", "/api/v1/benchmarks/discretionary", data=json.dumps({"signals": []}).encode()))

    # ── Print ──
    passed = sum(1 for r in results if r.ok)
    failed = sum(1 for r in results if not r.ok)

    for r in results:
        icon = "✅" if r.ok else "❌"
        print(f"{icon} {r.status:>3} {r.method:>4} {r.endpoint} ({r.response_ms}ms)" + (f"  ERR: {r.errors[0]}" if r.errors else ""))

    print(f"\nTotal: {len(results)} | Pass: {passed} | Fail: {failed}")

    # ── Save ──
    out = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "api_url": API_URL,
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "results": [asdict(r) for r in results],
    }
    with open(RESULTS_PATH, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nResults saved to {RESULTS_PATH}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
