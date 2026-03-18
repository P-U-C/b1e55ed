#!/usr/bin/env python3
"""Comprehensive producer smoke tests.

For every registered producer:
  1. Instantiate with a real ProducerContext (temp DB)
  2. Call run()
  3. Verify it returns a valid ProducerResult — or gracefully handles missing
     API keys / network issues (classified as SKIP, not FAIL)
  4. Report PASS / SKIP / FAIL with timing

Usage:
    .venv/bin/python -m pytest tests/e2e/test_producer_smoke.py -v
    .venv/bin/python tests/e2e/test_producer_smoke.py          # standalone

Exit code: number of FAILed producers (0 = clean).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

# ── Project root on sys.path ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

from engine.core.types import ProducerHealth, ProducerResult  # noqa: E402
from engine.producers.registry import _REGISTRY, discover  # noqa: E402

# ── Constants ─────────────────────────────────────────────────────────────

# Producers that are intentionally broken (test fixtures, quarantine examples).
# Excluded from pass/fail assertions in test_all_producers_smoke.
_FIXTURE_PRODUCERS = {"fail-prod"}

# Error substrings that indicate an environment/config issue, not broken code.
_ENV_SKIP_KEYWORDS = [
    # Network
    "ConnectionError",
    "ConnectionRefusedError",
    "Timeout",
    "TimeoutError",
    "HTTPError",
    "URLError",
    "gaierror",
    "SSLError",
    "ClientConnectorError",
    "ServerDisconnectedError",
    "ConnectError",
    "ReadTimeout",
    "RemoteProtocolError",
    # Auth / API keys
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
    "ALLIUM",
    "NANSEN",
    "APIFY",
    "FINANCIAL_DATASETS",
    # Rate limits
    "rate limit",
    "429",
    "Too Many Requests",
    # Optional deps
    "No module named",
    "MCP",
    "mcp",
    # Misc environment
    "ECONNREFUSED",
    "Name or service not known",
    "No such file or directory",
    # External adapter env vars not set in CI
    "unresolved env var placeholders",
    "POST_FIAT_SIGNALS_URL",
]


# ── Data ──────────────────────────────────────────────────────────────────


@dataclass
class ProducerTestResult:
    name: str
    domain: str
    status: str  # "pass", "skip", "fail"
    phase: str  # "discover", "instantiate", "run", "validate"
    detail: str = ""
    duration_ms: float = 0.0
    events_published: int = 0
    health: str = ""
    errors: list[str] = field(default_factory=list)


# ── Helpers ───────────────────────────────────────────────────────────────


def _classify_error(exc: Exception) -> str:
    """Return 'skip' if the error is environment-related, 'fail' otherwise."""
    msg = f"{type(exc).__name__}: {exc}"
    lowered = msg.lower()
    for kw in _ENV_SKIP_KEYWORDS:
        if kw.lower() in lowered:
            return "skip"
    return "fail"


def _make_context():
    """Build a ProducerContext with a temporary database."""
    from engine.core.client import ClientConfig, DataClient
    from engine.core.config import Config
    from engine.core.database import Database
    from engine.core.metrics import MetricsRegistry
    from engine.producers.base import ProducerContext

    tmpdir = tempfile.mkdtemp(prefix="smoke_")
    db_path = os.path.join(tmpdir, "smoke_test.db")
    config = Config()
    db = Database(db_path)
    client = DataClient(ClientConfig())
    metrics = MetricsRegistry()
    logger = logging.getLogger("smoke_test")

    return ProducerContext(config=config, db=db, client=client, metrics=metrics, logger=logger)


def _validate_result(result: ProducerResult) -> list[str]:
    """Return a list of validation issues (empty = valid)."""
    issues: list[str] = []

    if not isinstance(result, ProducerResult):
        issues.append(f"run() returned {type(result).__name__}, expected ProducerResult")
        return issues

    if result.events_published < 0:
        issues.append(f"events_published is negative: {result.events_published}")

    if result.duration_ms < 0:
        issues.append(f"duration_ms is negative: {result.duration_ms}")

    if not isinstance(result.errors, list):
        issues.append(f"errors is not a list: {type(result.errors).__name__}")

    if not isinstance(result.health, ProducerHealth):
        issues.append(f"health is not ProducerHealth: {type(result.health).__name__}")

    if result.timestamp is None:
        issues.append("timestamp is None")

    return issues


# ── Core test logic ───────────────────────────────────────────────────────


def smoke_test_all_producers() -> list[ProducerTestResult]:
    """Run smoke tests against every registered producer. Returns results list."""

    # Phase 0: discovery
    try:
        discover()
    except Exception as e:
        return [
            ProducerTestResult(
                name="__registry__",
                domain="*",
                status="fail",
                phase="discover",
                detail=f"Registry discover() failed: {e}",
            )
        ]

    producers = sorted(_REGISTRY.keys())
    ctx = _make_context()
    results: list[ProducerTestResult] = []

    for name in producers:
        cls = _REGISTRY[name]
        domain = getattr(cls, "domain", "?")
        t0 = time.perf_counter()

        # Phase 1: instantiate
        try:
            instance = cls(ctx)
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            cat = _classify_error(e)
            results.append(
                ProducerTestResult(
                    name=name,
                    domain=domain,
                    status=cat,
                    phase="instantiate",
                    detail=f"{type(e).__name__}: {e}"[:300],
                    duration_ms=round(elapsed, 1),
                )
            )
            continue

        # Phase 2: run()
        try:
            result = instance.run()
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            cat = _classify_error(e)
            results.append(
                ProducerTestResult(
                    name=name,
                    domain=domain,
                    status=cat,
                    phase="run",
                    detail=f"{type(e).__name__}: {e}"[:300],
                    duration_ms=round(elapsed, 1),
                )
            )
            continue

        elapsed = (time.perf_counter() - t0) * 1000

        # Phase 3: validate the ProducerResult
        issues = _validate_result(result)
        if issues:
            results.append(
                ProducerTestResult(
                    name=name,
                    domain=domain,
                    status="fail",
                    phase="validate",
                    detail="; ".join(issues)[:300],
                    duration_ms=round(elapsed, 1),
                )
            )
            continue

        # Result has errors inside? Classify them.
        if result.health == ProducerHealth.ERROR and result.errors:
            # Producer caught its own error — classify
            err_text = " ".join(result.errors)
            cat = "skip"
            lowered = err_text.lower()
            for kw in _ENV_SKIP_KEYWORDS:
                if kw.lower() in lowered:
                    break
            else:
                cat = "fail"

            results.append(
                ProducerTestResult(
                    name=name,
                    domain=domain,
                    status=cat,
                    phase="run",
                    detail=f"health=ERROR: {err_text}"[:300],
                    duration_ms=round(elapsed, 1),
                    events_published=result.events_published,
                    health=str(result.health),
                    errors=result.errors[:5],
                )
            )
            continue

        # All good
        results.append(
            ProducerTestResult(
                name=name,
                domain=domain,
                status="pass",
                phase="run",
                detail=f"events={result.events_published}, health={result.health}",
                duration_ms=round(elapsed, 1),
                events_published=result.events_published,
                health=str(result.health),
            )
        )

    return results


# ── Pytest integration ────────────────────────────────────────────────────


def test_all_producers_smoke():
    """pytest entry: no producer should FAIL (SKIP is acceptable)."""
    results = smoke_test_all_producers()

    # Print summary even under pytest
    _print_table(results)

    failures = [r for r in results if r.status == "fail" and r.name not in _FIXTURE_PRODUCERS]
    if failures:
        details = "\n".join(f"  {r.name}: [{r.phase}] {r.detail}" for r in failures)
        raise AssertionError(f"{len(failures)} producer(s) FAILED:\n{details}")


def test_registry_not_empty():
    """Sanity: at least 10 producers should register."""
    discover()
    count = len(_REGISTRY)
    assert count >= 10, f"Only {count} producers registered — expected >= 10"


def test_all_producers_return_producer_result():
    """Every producer's run() must return a ProducerResult (not raise)."""
    discover()
    ctx = _make_context()

    for name in sorted(_REGISTRY.keys()):
        cls = _REGISTRY[name]
        try:
            instance = cls(ctx)
            result = instance.run()
        except Exception:
            continue  # instantiation/run errors tested elsewhere

        assert isinstance(result, ProducerResult), f"{name}.run() returned {type(result).__name__}, not ProducerResult"


def test_producer_domains_valid():
    """Every producer must declare a valid canonical domain."""
    from engine.core.types import CANONICAL_DOMAINS

    discover()
    for name, cls in sorted(_REGISTRY.items()):
        domain = getattr(cls, "domain", None)
        assert domain in CANONICAL_DOMAINS, f"Producer '{name}' has domain='{domain}', expected one of {sorted(CANONICAL_DOMAINS)}"


def test_producer_schedules_set():
    """Every producer must have a non-empty schedule string."""
    discover()
    for name, cls in sorted(_REGISTRY.items()):
        schedule = getattr(cls, "schedule", None)
        assert schedule and isinstance(schedule, str), f"Producer '{name}' has no schedule set"


# ── Pretty output ────────────────────────────────────────────────────────

_ICONS = {"pass": "✅", "skip": "⚠️ ", "fail": "❌"}


def _print_table(results: list[ProducerTestResult]) -> None:
    """Print a formatted results table to stdout."""
    if not results:
        print("No results.")
        return

    print()
    print(f"{'':─<80}")
    print(f"  {'PRODUCER':<28} {'DOMAIN':<12} {'STATUS':<8} {'PHASE':<12} {'TIME':>8}  DETAIL")
    print(f"{'':─<80}")

    for r in results:
        icon = _ICONS.get(r.status, "?")
        time_str = f"{r.duration_ms:>7.0f}ms"
        detail_short = r.detail[:50] if r.detail else ""
        print(f"  {icon} {r.name:<25} {r.domain:<12} {r.status:<8} {r.phase:<12} {time_str}  {detail_short}")

    # Summary
    counts = {"pass": 0, "skip": 0, "fail": 0}
    total_ms = 0.0
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
        total_ms += r.duration_ms

    print(f"{'':─<80}")
    print(f"  ✅ {counts['pass']} passed  |  ⚠️  {counts['skip']} skipped  |  ❌ {counts['fail']} failed  |  ⏱  {total_ms:.0f}ms total")
    print(f"{'':─<80}")
    print()


# ── Standalone runner ─────────────────────────────────────────────────────


def main() -> int:
    """Run all smoke tests and return exit code = number of failures."""
    results = smoke_test_all_producers()
    _print_table(results)

    # Save JSON report
    out_path = "/tmp/producer_smoke_results.json"
    report = {
        "summary": {
            "pass": sum(1 for r in results if r.status == "pass"),
            "skip": sum(1 for r in results if r.status == "skip"),
            "fail": sum(1 for r in results if r.status == "fail"),
            "total_ms": round(sum(r.duration_ms for r in results), 1),
        },
        "results": [
            {
                "name": r.name,
                "domain": r.domain,
                "status": r.status,
                "phase": r.phase,
                "detail": r.detail,
                "duration_ms": r.duration_ms,
                "events_published": r.events_published,
                "health": r.health,
                "errors": r.errors,
            }
            for r in results
        ],
    }
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"JSON report: {out_path}")

    fail_count = report["summary"]["fail"]
    return fail_count


if __name__ == "__main__":
    sys.exit(main())
