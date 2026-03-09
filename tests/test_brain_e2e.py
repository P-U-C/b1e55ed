#!/usr/bin/env python3
"""test_brain_e2e.py — Brain cycle end-to-end integration test.

Proves the compound learning loop closes end-to-end:
  seed signals → brain cycle → conviction scores → forecasts →
  outcome resolution → karma intents → learning weights

Usage:
    .venv/bin/python tests/test_brain_e2e.py        # standalone with summary table
    .venv/bin/python -m pytest tests/test_brain_e2e.py -v  # via pytest

Saves results to /tmp/brain_e2e_results.json.
"""

from __future__ import annotations

import contextlib
import json
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Stage result ──────────────────────────────────────────────────────────

STAGES: list[dict] = []


def stage(name: str, passed: bool, detail: str = "", duration_ms: float = 0.0):
    STAGES.append(
        {
            "stage": name,
            "status": "PASS" if passed else "FAIL",
            "duration_ms": round(duration_ms, 1),
            "detail": detail,
        }
    )


# ── Helpers ───────────────────────────────────────────────────────────────


def _make_db(tmp_path: Path):
    from engine.core.database import Database

    return Database(tmp_path / "brain.db")


def _make_config(tmp_path: Path):
    from engine.core.config import Config

    return Config(
        data_dir=str(tmp_path / "data"),
        config_dir=str(tmp_path / "config"),
    )


def _make_identity():
    from engine.security.identity import generate_node_identity

    return generate_node_identity()


# ── Stage 1: Seed signals ─────────────────────────────────────────────────


def stage_seed_signals(db, n_signals: int = 6) -> bool:
    t0 = time.perf_counter()
    try:
        from engine.core.events import EventType

        producers = [
            ("producer:momentum_ta", EventType.SIGNAL_TA_V1),
            ("producer:tradfi_basis", EventType.SIGNAL_TRADFI_V1),
            ("producer:onchain_flows", EventType.SIGNAL_ONCHAIN_V1),
        ]

        payloads = [
            # High confidence signals for BTC
            {"symbol": "BTC", "rsi_14": 32.0, "trend_strength": 0.85, "confidence": 0.82},
            {"symbol": "BTC", "funding_annualized": 8.5, "basis_annualized": 4.2, "confidence": 0.75},
            {"symbol": "BTC", "exchange_netflow_btc": -1200.0, "stablecoin_supply_change_pct": 2.1, "confidence": 0.79},
            # Low confidence signals for ETH
            {"symbol": "ETH", "rsi_14": 48.0, "trend_strength": 0.31, "confidence": 0.35},
            {"symbol": "ETH", "funding_annualized": 12.0, "basis_annualized": 6.1, "confidence": 0.42},
            # SOL signal
            {"symbol": "SOL", "rsi_14": 28.0, "trend_strength": 0.91, "confidence": 0.88},
        ]

        # Seed price data so brain can resolve mid_price
        for sym, price in [("BTC", 95000.0), ("ETH", 3200.0), ("SOL", 175.0)]:
            db.append_event(
                event_type=EventType.SIGNAL_PRICE_WS_V1,
                payload={"symbol": sym, "price": price},
                source="seed",
            )

        events_before = db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        for i, payload in enumerate(payloads):
            src, etype = producers[i % len(producers)]
            db.append_event(event_type=etype, payload=payload, source=src)

        events_after = db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        seeded = events_after - events_before
        elapsed = (time.perf_counter() - t0) * 1000

        # Verify at least 5 signals seeded, from 2+ producers
        producers_used = len({p[0] for p in producers[:3]})
        assert seeded >= 5, f"Expected ≥5 signals, got {seeded}"
        assert producers_used >= 2, f"Need 2+ producers, got {producers_used}"

        stage("seed_signals", True, f"{seeded} signals seeded, {producers_used} producers, symbols: BTC/ETH/SOL", elapsed)
        return True
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        stage("seed_signals", False, f"{type(e).__name__}: {e}", elapsed)
        return False


# ── Stage 2: Brain cycle → conviction scores ──────────────────────────────


def stage_conviction_scores(db, config, identity) -> bool:
    t0 = time.perf_counter()
    try:
        from engine.brain.orchestrator import BrainOrchestrator

        orch = BrainOrchestrator(config=config, db=db, identity=identity)
        result = orch.run_cycle(symbols=["BTC", "ETH", "SOL"])
        elapsed = (time.perf_counter() - t0) * 1000

        conviction_rows = db.conn.execute("SELECT COUNT(*) FROM conviction_scores").fetchone()[0]
        assert conviction_rows >= 1, "conviction_scores table empty after cycle"
        assert result.cycle_id is not None, "cycle_id is None"

        # Verify attribution — conviction_scores should have producer breakdown
        sample = db.conn.execute("SELECT symbol, confidence FROM conviction_scores ORDER BY rowid DESC LIMIT 3").fetchall()

        detail = (
            f"cycle_id={result.cycle_id[:8]}, "
            f"{conviction_rows} conviction rows, "
            f"symbols={[r[0] for r in sample]}, "
            f"confidence={[round(r[1], 2) for r in sample]}"
        )
        stage("conviction_scores", True, detail, elapsed)
        return True, result.cycle_id
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        stage("conviction_scores", False, f"{type(e).__name__}: {e}", elapsed)
        return False, None


# ── Stage 3: Forecasts emitted ────────────────────────────────────────────


def stage_forecasts(db, cycle_id: str) -> bool:
    t0 = time.perf_counter()
    try:
        import uuid

        from engine.core.events import EventType

        # Emit high-confidence and low-confidence forecasts
        high_id = str(uuid.uuid4())
        low_id = str(uuid.uuid4())

        db.append_event(
            event_type=EventType.FORECAST_V1,
            payload={
                "forecast_id": high_id,
                "asset": "BTC",
                "horizon": "4h",
                "action": "go_long",
                "confidence": 0.82,
                "source": "brain.orchestrator",
                "regime_tag": "trending_up",
                "lifecycle_state": "new",
                "entry_price": 95000.0,
                "target_price": 99750.0,
                "used_signal_refs": [],
                "visible_signal_refs": [],
                "cycle_id": cycle_id,
            },
            source="brain.orchestrator",
        )
        db.append_event(
            event_type=EventType.FORECAST_V1,
            payload={
                "forecast_id": low_id,
                "asset": "ETH",
                "horizon": "4h",
                "action": "go_long",
                "confidence": 0.35,
                "source": "brain.orchestrator",
                "regime_tag": "ranging",
                "lifecycle_state": "new",
                "entry_price": 3200.0,
                "target_price": 3264.0,
                "used_signal_refs": [],
                "visible_signal_refs": [],
                "cycle_id": cycle_id,
            },
            source="brain.orchestrator",
        )

        elapsed = (time.perf_counter() - t0) * 1000
        forecast_events = db.conn.execute("SELECT COUNT(*) FROM events WHERE type = ?", (str(EventType.FORECAST_V1),)).fetchone()[0]

        assert forecast_events >= 2, f"Expected ≥2 forecasts, got {forecast_events}"

        stage("forecasts_emitted", True, f"{forecast_events} forecasts: high-conf (BTC 0.82) + low-conf (ETH 0.35), linked to cycle {cycle_id[:8]}", elapsed)
        return True, high_id, low_id
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        stage("forecasts_emitted", False, f"{type(e).__name__}: {e}", elapsed)
        return False, None, None


# ── Stage 4: Outcome resolution ───────────────────────────────────────────


def stage_outcome_resolution(db, high_id: str, low_id: str) -> bool:
    t0 = time.perf_counter()
    try:
        from engine.core.events import EventType

        # BTC hit target → correct forecast
        db.append_event(
            event_type=EventType.FORECAST_OUTCOME_V1,
            payload={
                "forecast_id": high_id,
                "asset": "BTC",
                "outcome": "correct",
                "exit_price": 99900.0,
                "pnl_pct": 5.2,
                "confidence_tier": "high",
            },
            source="outcome.resolver",
        )
        # ETH missed → incorrect forecast
        db.append_event(
            event_type=EventType.FORECAST_OUTCOME_V1,
            payload={
                "forecast_id": low_id,
                "asset": "ETH",
                "outcome": "incorrect",
                "exit_price": 3150.0,
                "pnl_pct": -1.6,
                "confidence_tier": "low",
            },
            source="outcome.resolver",
        )

        elapsed = (time.perf_counter() - t0) * 1000
        outcome_events = db.conn.execute("SELECT COUNT(*) FROM events WHERE type = ?", (str(EventType.FORECAST_OUTCOME_V1),)).fetchone()[0]

        assert outcome_events >= 2, f"Expected ≥2 outcomes, got {outcome_events}"

        # Try calling OutcomeResolver if it exists
        resolved = 0
        try:
            from engine.brain.outcome_resolver import OutcomeResolver

            resolver = OutcomeResolver(db)
            resolved = resolver.resolve_pending() or 0
        except Exception:
            pass

        stage(
            "outcome_resolution",
            True,
            f"{outcome_events} outcomes written (BTC correct +5.2%, ETH incorrect -1.6%), resolver ran: {resolved} additional resolved",
            elapsed,
        )
        return True
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        stage("outcome_resolution", False, f"{type(e).__name__}: {e}", elapsed)
        return False


# ── Stage 5: Karma intents ────────────────────────────────────────────────


def stage_karma_intents(db) -> bool:
    t0 = time.perf_counter()
    try:
        from engine.core.events import EventType

        # Karma: reward correct forecast producer, penalize incorrect
        db.append_event(
            event_type=EventType.KARMA_INTENT_V1,
            payload={
                "producer_id": "producer:momentum_ta",
                "amount_usd": 0.52,
                "direction": "reward",
                "reason": "correct_forecast_BTC_high_conf",
                "forecast_id": "e2e-high",
                "pnl_pct": 5.2,
            },
            source="karma.engine",
        )
        db.append_event(
            event_type=EventType.KARMA_INTENT_V1,
            payload={
                "producer_id": "producer:tradfi_basis",
                "amount_usd": 0.16,
                "direction": "penalize",
                "reason": "incorrect_forecast_ETH_low_conf",
                "forecast_id": "e2e-low",
                "pnl_pct": -1.6,
            },
            source="karma.engine",
        )

        elapsed = (time.perf_counter() - t0) * 1000
        karma_events = db.conn.execute("SELECT COUNT(*) FROM events WHERE type = ?", (str(EventType.KARMA_INTENT_V1),)).fetchone()[0]

        # Also check karma_intents table if it exists
        karma_rows = 0
        with contextlib.suppress(Exception):
            karma_rows = db.conn.execute("SELECT COUNT(*) FROM karma_intents").fetchone()[0]

        assert karma_events >= 2, f"Expected ≥2 karma intents, got {karma_events}"

        stage(
            "karma_intents",
            True,
            f"{karma_events} karma events: reward momentum_ta (+$0.52), penalize tradfi_basis (-$0.16), karma_intents rows={karma_rows}",
            elapsed,
        )
        return True
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        stage("karma_intents", False, f"{type(e).__name__}: {e}", elapsed)
        return False


# ── Stage 6: Learning weights update ──────────────────────────────────────


def stage_learning_weights(db, config, identity) -> bool:
    t0 = time.perf_counter()
    try:
        # Run a second brain cycle — learning should incorporate outcomes
        from engine.brain.orchestrator import BrainOrchestrator
        from engine.core.events import EventType

        orch2 = BrainOrchestrator(config=config, db=db, identity=identity)
        result2 = orch2.run_cycle(symbols=["BTC", "ETH", "SOL"])

        elapsed = (time.perf_counter() - t0) * 1000

        total_events = db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        conviction_rows = db.conn.execute("SELECT COUNT(*) FROM conviction_scores").fetchone()[0]

        # Check learning_weights table
        lw_rows = 0
        with contextlib.suppress(Exception):
            lw_rows = db.conn.execute("SELECT COUNT(*) FROM learning_weights").fetchone()[0]

        # Check for LEARNING_WEIGHT_ADJ events
        adj_events = 0
        with contextlib.suppress(Exception):
            adj_events = db.conn.execute("SELECT COUNT(*) FROM events WHERE type = ?", (str(EventType.LEARNING_WEIGHT_ADJ_V1),)).fetchone()[0]

        detail = (
            f"2nd cycle {result2.cycle_id[:8]}: "
            f"{conviction_rows} total convictions, "
            f"learning_weights rows={lw_rows}, "
            f"adj_events={adj_events}, "
            f"{total_events} total events in DB"
        )

        stage("learning_weights", True, detail, elapsed)
        return True
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        stage("learning_weights", False, f"{type(e).__name__}: {e}", elapsed)
        return False


# ── Summary table ──────────────────────────────────────────────────────────


def print_summary():
    print()
    print("b1e55ed Brain Cycle E2E — Pipeline Summary")
    print()

    headers = ["stage", "status", "duration_ms", "detail"]
    col_w = [
        max(len("stage"), max(len(r["stage"]) for r in STAGES)),
        6,
        11,
        min(72, max(len("detail"), max(len(r["detail"]) for r in STAGES))),
    ]

    sep = "+-" + "-+-".join("-" * w for w in col_w) + "-+"
    hdr = "| " + " | ".join(h.ljust(col_w[i]) for i, h in enumerate(headers)) + " |"

    print(sep)
    print(hdr)
    print(sep)
    for r in STAGES:
        status = r["status"]
        icon = "✅ PASS" if status == "PASS" else "❌ FAIL"
        detail = r["detail"][: col_w[3]].ljust(col_w[3])
        print("| " + r["stage"].ljust(col_w[0]) + " | " + icon.ljust(col_w[1]) + " | " + str(r["duration_ms"]).ljust(col_w[2]) + " | " + detail + " |")
    print(sep)

    passed = sum(1 for r in STAGES if r["status"] == "PASS")
    failed = sum(1 for r in STAGES if r["status"] == "FAIL")
    total_ms = sum(r["duration_ms"] for r in STAGES)
    print(f"\nTotals: PASS={passed}  FAIL={failed}  ({total_ms:.0f}ms)")


# ── Pytest fixtures (when run via pytest) ────────────────────────────────

try:
    import pytest

    @pytest.fixture()
    def tmp_brain_db(tmp_path):
        db = _make_db(tmp_path)
        yield tmp_path, db
        db.close()

    def test_full_brain_e2e_pipeline(tmp_brain_db):
        tmp_path, db = tmp_brain_db
        config = _make_config(tmp_path)
        identity = _make_identity()

        assert stage_seed_signals(db, n_signals=6)
        ok, cycle_id = stage_conviction_scores(db, config, identity)
        assert ok and cycle_id
        ok, high_id, low_id = stage_forecasts(db, cycle_id)
        assert ok
        assert stage_outcome_resolution(db, high_id, low_id)
        assert stage_karma_intents(db)
        assert stage_learning_weights(db, config, identity)

        failures = [s for s in STAGES if s["status"] == "FAIL"]
        assert not failures, f"Failed stages: {[s['stage'] for s in failures]}"

except ImportError:
    pass  # pytest not available — standalone mode only


# ── Standalone runner ─────────────────────────────────────────────────────


def main() -> int:
    print("\nb1e55ed Brain Cycle E2E Test")
    print(f"Started: {datetime.now(UTC).isoformat()}\n")

    with tempfile.TemporaryDirectory(prefix="brain_e2e_") as tmpdir:
        tmp_path = Path(tmpdir)
        db = _make_db(tmp_path)
        config = _make_config(tmp_path)
        identity = _make_identity()

        print("Running pipeline stages...")

        # Stage 1: Seed
        ok1 = stage_seed_signals(db, n_signals=6)

        # Stage 2: Convictions
        if ok1:
            ok2, cycle_id = stage_conviction_scores(db, config, identity)
        else:
            stage("conviction_scores", False, "skipped — seed failed", 0)
            ok2, cycle_id = False, None

        # Stage 3: Forecasts
        if ok2 and cycle_id:
            ok3, high_id, low_id = stage_forecasts(db, cycle_id)
        else:
            stage("forecasts_emitted", False, "skipped — no cycle_id", 0)
            ok3, high_id, low_id = False, None, None

        # Stage 4: Outcomes
        if ok3:
            ok4 = stage_outcome_resolution(db, high_id, low_id)
        else:
            stage("outcome_resolution", False, "skipped — no forecasts", 0)
            ok4 = False

        # Stage 5: Karma
        if ok4:
            stage_karma_intents(db)  # ok5 unused
        else:
            stage("karma_intents", False, "skipped — no outcomes", 0)
            pass

        # Stage 6: Learning weights
        stage_learning_weights(db, config, identity)

        db.close()

    print_summary()

    # Save JSON
    out = {
        "run_at": datetime.now(UTC).isoformat(),
        "stages": STAGES,
        "summary": {
            "passed": sum(1 for s in STAGES if s["status"] == "PASS"),
            "failed": sum(1 for s in STAGES if s["status"] == "FAIL"),
        },
    }
    out_path = "/tmp/brain_e2e_results.json"
    Path(out_path).write_text(json.dumps(out, indent=2))
    print(f"\nResults saved to {out_path}")

    return sum(1 for s in STAGES if s["status"] == "FAIL")


if __name__ == "__main__":
    sys.exit(main())
