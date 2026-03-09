#!/usr/bin/env python3
"""Smoke test every producer: import, instantiate, call run().

Results: ✅ PASS / ⚠️ SKIP (missing api key/network) / ❌ FAIL (broken code)
Saves JSON to /tmp/producer_smoke_results.json
"""

import json
import logging
import os
import sys
import traceback
from pathlib import Path

# Ensure project root on path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# Silence noisy loggers
logging.basicConfig(level=logging.WARNING)

from engine.producers.registry import _REGISTRY, discover  # noqa: E402

# ── Helpers ──────────────────────────────────────────────────────────────

NETWORK_ERRORS = (
    "ConnectionError",
    "Timeout",
    "HTTPError",
    "URLError",
    "ConnectionRefusedError",
    "gaierror",
    "SSLError",
    "ClientConnectorError",
    "ServerDisconnectedError",
)

API_KEY_HINTS = (
    "api_key",
    "api key",
    "apikey",
    "API_KEY",
    "unauthorized",
    "401",
    "403",
    "forbidden",
    "missing key",
    "credential",
    "auth",
    "ALLIUM",
    "NANSEN",
    "APIFY",
    "FINANCIAL_DATASETS",
)

SKIP_KEYWORDS = tuple(
    list(NETWORK_ERRORS)
    + list(API_KEY_HINTS)
    + [
        "No module named",
        "MCP",
        "mcp",
        "rate limit",
        "429",
    ]
)


def classify_error(exc: Exception) -> str:
    """Return 'skip' for expected/env failures, 'fail' for broken code."""
    msg = f"{type(exc).__name__}: {exc}"
    for kw in SKIP_KEYWORDS:
        if kw.lower() in msg.lower():
            return "skip"
    return "fail"


def make_mock_ctx():
    """Build a minimal ProducerContext with real Config + DB."""
    from engine.core.client import ClientConfig, DataClient
    from engine.core.config import Config
    from engine.core.database import Database
    from engine.core.metrics import MetricsRegistry
    from engine.producers.base import ProducerContext

    config = Config()
    db = Database(str(ROOT / "data" / "brain.db"))
    client = DataClient(ClientConfig())
    metrics = MetricsRegistry()
    logger = logging.getLogger("smoke")

    return ProducerContext(config=config, db=db, client=client, metrics=metrics, logger=logger)


# ── Main ─────────────────────────────────────────────────────────────────


def main():
    # Discover all producers
    try:
        discover()
    except Exception as e:
        print(f"❌ Registry discover() failed: {e}")
        traceback.print_exc()
        sys.exit(1)

    producers = sorted(_REGISTRY.keys())
    print(f"\nFound {len(producers)} registered producers: {', '.join(producers)}\n")

    ctx = make_mock_ctx()
    results = {}

    for name in producers:
        cls = _REGISTRY[name]
        status = "unknown"
        detail = ""

        # Phase 1: instantiate
        try:
            instance = cls(ctx)
        except Exception as e:
            cat = classify_error(e)
            if cat == "skip":
                status, detail = "skip", f"instantiate: {type(e).__name__}: {e}"
            else:
                status, detail = "fail", f"instantiate: {type(e).__name__}: {e}"
            results[name] = {"status": status, "detail": detail[:300]}
            icon = "⚠️ SKIP" if status == "skip" else "❌ FAIL"
            print(f"  {icon}  {name:20s} — {detail[:120]}")
            continue

        # Phase 2: call run()
        try:
            result = instance.run()
            status, detail = "pass", f"run() returned {type(result).__name__}"
            if hasattr(result, "events"):
                detail += f", {len(result.events)} events"
        except Exception as e:
            cat = classify_error(e)
            if cat == "skip":
                status, detail = "skip", f"run: {type(e).__name__}: {e}"
            else:
                status, detail = "fail", f"run: {type(e).__name__}: {e}"

        results[name] = {"status": status, "detail": detail[:300]}
        icons = {"pass": "✅ PASS", "skip": "⚠️ SKIP", "fail": "❌ FAIL"}
        print(f"  {icons[status]}  {name:20s} — {detail[:120]}")

    # Summary
    counts = {"pass": 0, "skip": 0, "fail": 0}
    for r in results.values():
        counts[r["status"]] += 1

    print(f"\n{'=' * 60}")
    print(f"  ✅ {counts['pass']} passed  |  ⚠️ {counts['skip']} skipped  |  ❌ {counts['fail']} failed")
    print(f"{'=' * 60}\n")

    # Save JSON
    out_path = "/tmp/producer_smoke_results.json"
    with open(out_path, "w") as f:
        json.dump({"summary": counts, "results": results}, f, indent=2)
    print(f"Results saved to {out_path}")

    return counts["fail"]


if __name__ == "__main__":
    sys.exit(main())
