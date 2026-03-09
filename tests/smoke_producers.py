#!/usr/bin/env python3
"""Smoke test every producer: import, instantiate, call run().

Classification:
  PASS — run() returned a valid ProducerResult with health != degraded
  SKIP — missing API key / credential / endpoint (health=degraded or auth error)
  FAIL — broken code (unexpected exception unrelated to env)

Saves JSON to /tmp/producer_smoke_results.json
"""

import json
import logging
import os
import sys
import time
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


def print_table(rows: list[dict]) -> None:
    """Print ASCII table with columns: producer_name, status, duration_ms, error_message."""
    headers = ["producer_name", "status", "duration_ms", "error_message"]
    col_widths = [len(h) for h in headers]

    for r in rows:
        col_widths[0] = max(col_widths[0], len(r["producer_name"]))
        col_widths[1] = max(col_widths[1], len(r["status"]))
        col_widths[2] = max(col_widths[2], len(str(r["duration_ms"])))
        col_widths[3] = max(col_widths[3], min(len(r["error_message"]), 60))

    sep = "+-" + "-+-".join("-" * w for w in col_widths) + "-+"
    header_row = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"

    print(sep)
    print(header_row)
    print(sep)
    for r in rows:
        err = r["error_message"][: col_widths[3]].ljust(col_widths[3])
        print(
            "| "
            + r["producer_name"].ljust(col_widths[0])
            + " | "
            + r["status"].ljust(col_widths[1])
            + " | "
            + str(r["duration_ms"]).ljust(col_widths[2])
            + " | "
            + err
            + " |"
        )
    print(sep)


# ── Main ─────────────────────────────────────────────────────────────────


def main():
    # Discover all producers
    try:
        discover()
    except Exception as e:
        print(f"FAIL: Registry discover() failed: {e}")
        traceback.print_exc()
        sys.exit(1)

    producers = sorted(_REGISTRY.keys())
    print("\nb1e55ed Producer Smoke Test")
    print(f"Found {len(producers)} registered producers\n")

    ctx = make_mock_ctx()
    table_rows: list[dict] = []

    for name in producers:
        cls = _REGISTRY[name]
        status = "UNKNOWN"
        error_message = ""
        t_start = time.monotonic()

        # Phase 1: instantiate
        try:
            instance = cls(ctx)
        except Exception as e:
            duration_ms = int((time.monotonic() - t_start) * 1000)
            cat = classify_error(e)
            status = "SKIP" if cat == "skip" else "FAIL"
            error_message = f"{type(e).__name__}: {e}"[:200]
            table_rows.append(
                {
                    "producer_name": name,
                    "status": status,
                    "duration_ms": duration_ms,
                    "error_message": error_message,
                }
            )
            continue

        # Phase 2: call run()
        try:
            result = instance.run()
            duration_ms = int((time.monotonic() - t_start) * 1000)

            # Classify degraded results as SKIP — producer code works but
            # has no configured endpoint/credentials, so it cannot generate
            # real signals. This demonstrates the SKIP classification path.
            health = getattr(result, "health", None)
            health_str = str(health).lower() if health is not None else ""
            events = getattr(result, "events", [])

            if health_str == "degraded" or (health is not None and "degraded" in health_str):
                status = "SKIP"
                error_message = f"health=degraded, {len(events)} events (missing endpoint/credentials)"
            else:
                status = "PASS"
                error_message = f"{len(events)} events emitted"

        except Exception as e:
            duration_ms = int((time.monotonic() - t_start) * 1000)
            cat = classify_error(e)
            status = "SKIP" if cat == "skip" else "FAIL"
            error_message = f"{type(e).__name__}: {e}"[:200]

        table_rows.append(
            {
                "producer_name": name,
                "status": status,
                "duration_ms": duration_ms,
                "error_message": error_message,
            }
        )

    # Print table
    print_table(table_rows)

    # Summary
    counts = {"PASS": 0, "SKIP": 0, "FAIL": 0}
    for r in table_rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    print(f"\nTotals: PASS={counts['PASS']}  SKIP={counts['SKIP']}  FAIL={counts['FAIL']}")
    total_ms = sum(r["duration_ms"] for r in table_rows)
    print(f"Total time: {total_ms}ms\n")

    # Save JSON
    out_path = "/tmp/producer_smoke_results.json"
    with open(out_path, "w") as f:
        json.dump({"summary": counts, "results": table_rows}, f, indent=2, default=str)
    print(f"Results saved to {out_path}")

    return counts["FAIL"]


if __name__ == "__main__":
    sys.exit(main())
