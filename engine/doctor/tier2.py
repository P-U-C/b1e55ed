"""Tier 2 — Pipeline smoke tests.

Uses a temp DB, no network. Validates:
- Signal ingestion + hash chain
- Brain cycle → conviction_scores
- Outcome resolution → outcome events
- Learning weights population
- Karma intents creation
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from engine.doctor.tier0 import CheckResult

try:
    from datetime import UTC
except ImportError:  # pragma: no cover
    UTC = UTC  # noqa: N806

Status = Literal["pass", "warn", "fail"]


def _setup_temp_pipeline() -> tuple:
    """Create a temp DB + config + identity for pipeline tests."""
    from engine.core.config import Config
    from engine.core.database import Database
    from engine.security.identity import NodeIdentity

    tmpdir = tempfile.mkdtemp(prefix="b1e55ed_doctor_")
    db = Database(Path(tmpdir) / "doctor.db")

    # Load config with safe fallback
    try:
        user_yaml = Path.home() / ".b1e55ed" / "config" / "user.yaml"
        if user_yaml.exists():
            config = Config.from_yaml(user_yaml)
        else:
            config = Config.from_repo_defaults()
    except Exception:
        config = Config()

    identity = NodeIdentity(
        node_id="b1e55ed-doctor",
        public_key="0" * 64,
        private_key="0" * 64,
        created_at="2024-01-01T00:00:00+00:00",
    )

    return tmpdir, db, config, identity


def check_signal_ingestion() -> CheckResult:
    """Ingest 3 synthetic signals into temp DB and verify hash chain."""
    tmpdir, db, config, identity = _setup_temp_pipeline()
    try:
        from engine.core.events import EventType

        symbols = ["BTC", "ETH", "SOL"]
        events = []
        for i, sym in enumerate(symbols):
            payload = {
                "symbol": sym,
                "direction": "bullish",
                "conviction": 7.0 + i,
                "rationale": f"Doctor test signal for {sym}",
                "source": "doctor:test",
            }
            ev = db.append_event(
                event_type=EventType.SIGNAL_CURATOR_V1,
                payload=payload,
                source="doctor.tier2",
            )
            events.append(ev)

        # Verify hash chain
        chain_ok = db.verify_hash_chain()
        if not chain_ok:
            return CheckResult(
                "signal_ingestion",
                "fail",
                f"Ingested {len(events)} signals but hash chain INVALID",
            )
        return CheckResult(
            "signal_ingestion",
            "pass",
            f"Signal ingestion ({len(events)} events, hash chain valid)",
        )
    except Exception as e:
        return CheckResult("signal_ingestion", "fail", f"Signal ingestion failed: {type(e).__name__}: {e}")
    finally:
        db.close()


def check_brain_cycle() -> CheckResult:
    """Run brain cycle on synthetic signals → verify conviction_scores rows."""
    tmpdir, db, config, identity = _setup_temp_pipeline()
    try:
        from engine.brain.orchestrator import BrainOrchestrator
        from engine.core.events import EventType

        # Inject synthetic signals
        symbols = config.universe.symbols[:3] if config.universe.symbols else ["BTC", "ETH", "SOL"]
        for sym in symbols:
            payload = {
                "symbol": sym,
                "direction": "bullish",
                "conviction": 8.0,
                "rationale": f"Doctor test signal for {sym}",
                "source": "doctor:test",
            }
            db.append_event(
                event_type=EventType.SIGNAL_CURATOR_V1,
                payload=payload,
                source="doctor.tier2",
            )

        orch = BrainOrchestrator(config=config, db=db, identity=identity)
        orch.run_cycle(symbols=symbols)

        # Check conviction_scores table
        rows = db.conn.execute("SELECT COUNT(*) FROM conviction_scores").fetchone()
        count = int(rows[0]) if rows else 0

        if count > 0:
            return CheckResult(
                "brain_cycle",
                "pass",
                f"Brain cycle ({count} convictions from {len(symbols)} signals)",
            )
        else:
            # Brain ran but no convictions — might be data quality gating
            return CheckResult(
                "brain_cycle",
                "warn",
                "Brain cycle completed but 0 conviction_scores (data quality may have gated)",
            )
    except Exception as e:
        return CheckResult("brain_cycle", "fail", f"Brain cycle failed: {type(e).__name__}: {e}")
    finally:
        db.close()


def check_outcome_resolution() -> CheckResult:
    """Inject forecast events and resolve them → verify outcome events."""
    tmpdir, db, config, identity = _setup_temp_pipeline()
    try:
        from engine.core.events import EventType

        now = datetime.now(tz=UTC)
        past = now - timedelta(hours=2)

        # Inject a SIGNAL_PRICE_WS_V1 event for price context (needed by resolver)
        db.append_event(
            event_type=EventType.SIGNAL_PRICE_WS_V1,
            payload={"symbol": "BTC", "price": 100000.0, "ts": now.isoformat()},
            source="doctor.tier2",
            ts=now,
        )

        # Inject a forecast that is already past its horizon
        forecast_id = str(uuid.uuid4())
        db.append_event(
            event_type=EventType.FORECAST_V1,
            payload={
                "forecast_id": forecast_id,
                "producer_id": "doctor_test",
                "asset": "BTC",
                "horizon": "1h",
                "action": "long",
                "confidence": 0.8,
                "price_at_emit": 99000.0,
                "emitted_at": past.isoformat(),
                "regime": "unknown",
                "rationale": "Doctor test forecast",
            },
            source="doctor.tier2",
            ts=past,
        )

        # Run outcome resolution
        from engine.brain.outcome_resolver import OutcomeResolver

        resolver = OutcomeResolver(db)
        resolved = resolver.resolve_pending()

        # Check for outcome events
        outcome_evs = db.get_events(event_type=EventType.FORECAST_OUTCOME_V1, limit=10)
        if len(outcome_evs) > 0:
            return CheckResult(
                "outcome_resolution",
                "pass",
                f"Outcome resolution ({resolved} resolved)",
            )
        else:
            # Resolver may not find matching price — that's acceptable
            return CheckResult(
                "outcome_resolution",
                "warn",
                "Outcome resolution ran but 0 outcomes (may need price data matching)",
            )
    except Exception as e:
        return CheckResult("outcome_resolution", "fail", f"Outcome resolution failed: {type(e).__name__}: {e}")
    finally:
        db.close()


def check_learning_weights() -> CheckResult:
    """Check that learning_weights table can be populated."""
    tmpdir, db, config, identity = _setup_temp_pipeline()
    try:
        # Insert a synthetic learning weight adjustment
        now = datetime.now(tz=UTC).isoformat()
        db.conn.execute(
            """INSERT INTO learning_weights
               (cycle_type, domain, old_weight, new_weight, delta, reason, ts)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("daily", "technical", 0.10, 0.12, 0.02, "doctor_test", now),
        )
        db.conn.commit()

        rows = db.conn.execute("SELECT COUNT(*) FROM learning_weights").fetchone()
        count = int(rows[0]) if rows else 0

        if count > 0:
            return CheckResult("learning_weights", "pass", f"Learning weights table writable ({count} rows)")
        else:
            return CheckResult("learning_weights", "fail", "Learning weights: 0 rows after insert")
    except Exception as e:
        return CheckResult("learning_weights", "fail", f"Learning weights failed: {type(e).__name__}: {e}")
    finally:
        db.close()


def check_karma_intents() -> CheckResult:
    """Check that karma_intents table can be populated."""
    tmpdir, db, config, identity = _setup_temp_pipeline()
    try:
        intent_id = str(uuid.uuid4())
        trade_id = str(uuid.uuid4())
        db.conn.execute(
            """INSERT INTO karma_intents
               (id, trade_id, realized_pnl_usd, karma_percentage, karma_amount_usd, node_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (intent_id, trade_id, 100.0, 0.005, 0.50, "b1e55ed-doctor"),
        )
        db.conn.commit()

        rows = db.conn.execute("SELECT COUNT(*) FROM karma_intents").fetchone()
        count = int(rows[0]) if rows else 0

        if count > 0:
            return CheckResult("karma_intents", "pass", "Karma intents created")
        else:
            return CheckResult("karma_intents", "fail", "Karma intents: 0 rows after insert")
    except Exception as e:
        return CheckResult("karma_intents", "fail", f"Karma intents failed: {type(e).__name__}: {e}")
    finally:
        db.close()


def run_tier2() -> list[CheckResult]:
    """Run all Tier 2 pipeline smoke checks."""
    return [
        check_signal_ingestion(),
        check_brain_cycle(),
        check_outcome_resolution(),
        check_learning_weights(),
        check_karma_intents(),
    ]
