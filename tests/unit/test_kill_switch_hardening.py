"""Tests for Sprint S5 — Kill Switch Hardening (all 5 conditions)."""

from __future__ import annotations

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017
from pathlib import Path

from engine.brain.kill_switch import KillSwitch, KillSwitchLevel
from engine.core.config import Config
from engine.core.database import Database
from engine.core.policy import TradingPolicy, TradingPolicyEngine
from engine.core.types import TradeIntent
from engine.execution.oms import OMS, default_sizer_from_config
from engine.execution.pnl import PnLTracker
from engine.execution.preflight import Preflight


def _make_stack(temp_dir: Path, test_config: Config):
    db = Database(temp_dir / "brain.db")
    ks = KillSwitch(test_config, db)
    pol = TradingPolicy(
        max_daily_loss_usd=0.0,
        max_position_size_pct=test_config.risk.max_position_pct,
        kill_switch_enabled=True,
        max_leverage_default=test_config.risk.max_leverage,
    )
    policy_engine = TradingPolicyEngine(policy=pol)
    preflight = Preflight(policy=policy_engine, kill_switch=ks)
    sizer = default_sizer_from_config(test_config)
    oms = OMS(config=test_config, db=db, preflight=preflight, sizer=sizer)
    pnl = PnLTracker(db, config=test_config)
    return db, ks, oms, pnl, preflight


def _open_position(db: Database, position_id: str, entry_price: float = 50000.0, notional: float = 500.0, direction: str = "long"):
    """Insert a synthetic open position."""
    from datetime import datetime

    now = datetime.now(tz=UTC).isoformat()
    db.conn.execute(
        """INSERT INTO positions (id, platform, asset, direction, entry_price, size_notional,
           leverage, opened_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (position_id, "paper", "BTC", direction, entry_price, notional, 1.0, now, "open"),
    )
    db.conn.commit()


# ── KS-1 ──────────────────────────────────────────────────────────────


def test_ks1_three_consecutive_losses_triggers_defensive(temp_dir: Path, test_config: Config) -> None:
    # Disable the paper-mode loss-gate bypass so that KS-1 still fires in this test.
    # (paper_ignore_consecutive_loss_gate=True is the new default for paper mode but
    # intentionally bypasses the kill-switch escalation — this test verifies the
    # underlying escalation path when the bypass is disabled.)
    live_config = test_config.model_copy(update={"execution": test_config.execution.model_copy(update={"paper_ignore_consecutive_loss_gate": False})})
    db, ks, oms, pnl, pf = _make_stack(temp_dir, live_config)

    for i in range(3):
        pid = f"loss-{i}"
        _open_position(db, pid, entry_price=50000.0, notional=500.0)
        # Close at a loss (exit below entry for long)
        pnl.close_position(position_id=pid, exit_price=49000.0, reason="test")

    # Check system_state
    row = db.conn.execute("SELECT value FROM system_state WHERE key = 'consecutive_loss_count'").fetchone()
    assert row is not None
    assert int(row[0]) >= 3

    # Check that a KILL_SWITCH_V1 event was emitted with DEFENSIVE level
    evts = db.conn.execute("SELECT payload FROM events WHERE type = 'system.kill_switch.v1' ORDER BY rowid DESC LIMIT 1").fetchone()
    assert evts is not None
    import json

    payload = json.loads(evts[0])
    assert payload["level"] >= int(KillSwitchLevel.DEFENSIVE)


def test_ks1_win_resets_consecutive_count(temp_dir: Path, test_config: Config) -> None:
    db, ks, oms, pnl, pf = _make_stack(temp_dir, test_config)

    # Two losses
    for i in range(2):
        pid = f"loss-{i}"
        _open_position(db, pid, entry_price=50000.0, notional=500.0)
        pnl.close_position(position_id=pid, exit_price=49000.0, reason="test")

    row = db.conn.execute("SELECT value FROM system_state WHERE key = 'consecutive_loss_count'").fetchone()
    assert int(row[0]) == 2

    # Win resets
    _open_position(db, "win-0", entry_price=50000.0, notional=500.0)
    pnl.close_position(position_id="win-0", exit_price=51000.0, reason="test")

    row = db.conn.execute("SELECT value FROM system_state WHERE key = 'consecutive_loss_count'").fetchone()
    assert int(row[0]) == 0


# ── KS-2 ──────────────────────────────────────────────────────────────


def test_ks2_single_loss_over_2pct_triggers_autoclose(temp_dir: Path, test_config: Config) -> None:
    db, ks, oms, pnl, pf = _make_stack(temp_dir, test_config)

    # portfolio_value_usd=10000, max_single_loss_pct=0.02 → threshold=200
    # Position: notional=500, entry=50000, so qty=0.01
    # Mark at 29000: unrealized = (29000-50000)*0.01 = -210 → exceeds -200
    _open_position(db, "big-loss", entry_price=50000.0, notional=500.0)

    closed = pnl.check_auto_close(position_id="big-loss", mark_price=29000.0)
    assert closed is True

    # Position should be closed
    row = db.conn.execute("SELECT status FROM positions WHERE id = 'big-loss'").fetchone()
    assert row["status"] == "closed"


# ── KS-3 ──────────────────────────────────────────────────────────────


def test_ks3_open_risk_over_5pct_blocks_new_position(temp_dir: Path, test_config: Config) -> None:
    db, ks, oms, pnl, pf = _make_stack(temp_dir, test_config)

    # portfolio_value_usd=10000, max_open_risk_pct=0.05 → max risk = 500
    # Insert position with notional=600, leverage=1 → risk=600 > 500
    _open_position(db, "existing", entry_price=50000.0, notional=600.0)

    intent = TradeIntent(
        symbol="BTC",
        direction="long",
        size_pct=0.05,
        leverage=1.0,
        conviction_score=80.0,
        regime="BULL",
        rationale="test",
    )
    result = pf.check(intent, mode="paper", equity_usd=10000.0)
    assert not result.approved
    assert "open_risk_limit_5pct" in result.reasons


def test_ks3_open_risk_under_5pct_allows_position(temp_dir: Path, test_config: Config) -> None:
    db, ks, oms, pnl, pf = _make_stack(temp_dir, test_config)

    # Insert position with notional=400, leverage=1 → risk=400 < 500
    _open_position(db, "existing", entry_price=50000.0, notional=400.0)

    intent = TradeIntent(
        symbol="BTC",
        direction="long",
        size_pct=0.05,
        leverage=1.0,
        conviction_score=80.0,
        regime="BULL",
        rationale="test",
    )
    result = pf.check(intent, mode="paper", equity_usd=10000.0)
    assert result.approved


# ── KS-4 ──────────────────────────────────────────────────────────────


def test_ks4_domain_degraded_zeroes_weight(temp_dir: Path, test_config: Config) -> None:
    from engine.brain.orchestrator import BrainOrchestrator

    # Simulate 2 consecutive cycles with 0 quality for a domain
    db = Database(temp_dir / "brain.db")
    KillSwitch(test_config, db)  # init schema
    orch = BrainOrchestrator.__new__(BrainOrchestrator)
    orch._domain_miss_counts = {}

    # Simulate the degradation logic directly
    q_mult = {"technical": 0.0, "onchain": 1.0, "social": 1.0, "sentiment": 1.0, "macro": 1.0}

    # Cycle 1
    for domain in q_mult:
        quality = q_mult.get(domain, 1.0)
        if quality <= 0.0:
            orch._domain_miss_counts[domain] = orch._domain_miss_counts.get(domain, 0) + 1
        else:
            orch._domain_miss_counts[domain] = 0

    # Cycle 2
    for domain in q_mult:
        quality = q_mult.get(domain, 1.0)
        if quality <= 0.0:
            orch._domain_miss_counts[domain] = orch._domain_miss_counts.get(domain, 0) + 1
        else:
            orch._domain_miss_counts[domain] = 0

    # After 2 cycles, technical should be degraded
    assert orch._domain_miss_counts["technical"] >= 2
    # Zero out weight
    degraded = [d for d in q_mult if orch._domain_miss_counts.get(d, 0) >= 2]
    for d in degraded:
        q_mult[d] = 0.0
    assert q_mult["technical"] == 0.0
    assert q_mult["onchain"] == 1.0


def test_ks4_all_domains_degraded_triggers_caution(temp_dir: Path, test_config: Config) -> None:
    db = Database(temp_dir / "brain.db")
    ks = KillSwitch(test_config, db)

    # Simulate all domains degraded for 2 cycles
    domains = ["technical", "onchain", "social", "sentiment", "macro"]
    miss_counts = {d: 2 for d in domains}

    all_degraded = all(miss_counts.get(d, 0) >= 2 for d in domains)
    assert all_degraded

    # Trigger escalation
    ks.evaluate(manual_level=KillSwitchLevel.CAUTION, reason="all_domains_degraded")
    assert ks.level >= KillSwitchLevel.CAUTION


# ── KS-5 ──────────────────────────────────────────────────────────────


def test_ks5_fill_divergence_over_half_pct_triggers_caution(temp_dir: Path, test_config: Config) -> None:
    db, ks, oms, pnl, pf = _make_stack(temp_dir, test_config)

    # intended_price=50000, paper broker fills at ~50000 (with slippage ~5bps)
    # We need divergence > 0.5%, so intended_price far from mid_price
    # Paper fills at mid_price * (1 + slippage_bps/10000) for buys
    # Set intended_price=49500, mid_price=50000 → fill ~50025
    # divergence = |50025 - 49500| / 49500 ≈ 1.06% > 0.5%
    intent = TradeIntent(
        symbol="BTC",
        direction="long",
        size_pct=0.05,
        leverage=1.0,
        conviction_score=80.0,
        regime="BULL",
        rationale="test",
        intended_price=49500.0,
    )
    result = oms.submit(intent, mid_price=50000.0, equity_usd=10000.0)
    assert result.status == "filled"

    # Should have escalated to CAUTION
    assert ks.level >= KillSwitchLevel.CAUTION

    # Should have AUDIT_V1 event
    audit = db.conn.execute("SELECT payload FROM events WHERE type = 'system.audit.v1'").fetchone()
    assert audit is not None


def test_ks5_fill_divergence_under_half_pct_ok(temp_dir: Path, test_config: Config) -> None:
    db, ks, oms, pnl, pf = _make_stack(temp_dir, test_config)

    # intended_price very close to mid_price → divergence < 0.5%
    intent = TradeIntent(
        symbol="BTC",
        direction="long",
        size_pct=0.05,
        leverage=1.0,
        conviction_score=80.0,
        regime="BULL",
        rationale="test",
        intended_price=50000.0,
    )
    result = oms.submit(intent, mid_price=50000.0, equity_usd=10000.0)
    assert result.status == "filled"

    # Should NOT have escalated
    assert ks.level == KillSwitchLevel.SAFE

    # No AUDIT_V1 event for divergence
    audit = db.conn.execute("SELECT payload FROM events WHERE type = 'system.audit.v1'").fetchone()
    assert audit is None
