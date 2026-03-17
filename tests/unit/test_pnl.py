from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from engine.core.config import Config
from engine.core.database import Database
from engine.execution.paper import PaperBroker, PaperConfig
from engine.execution.pnl import PnLTracker


def test_unrealized_and_realized_pnl_long(temp_dir: Path) -> None:
    db = Database(temp_dir / "brain.db")
    broker = PaperBroker(db)
    pnl = PnLTracker(db)

    fill = broker.execute_market(
        symbol="BTC",
        direction="long",
        notional_usd=1000.0,
        leverage=1.0,
        mid_price=50_000.0,
        idempotency_key="pnl1",
    )

    u = pnl.unrealized_usd(position_id=fill.position_id, mark_price=55_000.0)
    assert u > 0

    r = pnl.close_position(position_id=fill.position_id, exit_price=55_000.0, reason="tp")
    assert r > 0

    # can't close twice
    with pytest.raises(ValueError):
        pnl.close_position(position_id=fill.position_id, exit_price=55_000.0)


def test_expire_stale_positions_closes_old_position(temp_dir: Path) -> None:
    """expire_stale_positions closes a position older than paper_max_hold_hours."""
    db = Database(temp_dir / "brain.db")
    cfg = Config.from_repo_defaults()
    # Force paper mode and short expiry
    object.__setattr__(cfg.execution, "mode", "paper")
    object.__setattr__(cfg.execution, "paper_max_hold_hours", 1)

    broker = PaperBroker(db, config=PaperConfig(max_positions_per_symbol=2))
    pnl = PnLTracker(db, config=cfg)

    fill = broker.execute_market(
        symbol="SOL",
        direction="long",
        notional_usd=500.0,
        leverage=1.0,
        mid_price=100.0,
        idempotency_key="ts-1",
    )

    # Backdate position to 2 hours ago so it exceeds the 1h threshold
    two_hours_ago = datetime(2020, 1, 1, 0, 0, 0, tzinfo=UTC).isoformat()
    db.execute(
        "UPDATE positions SET opened_at = ? WHERE id = ?",
        (two_hours_ago, fill.position_id),
    )

    closed = pnl.expire_stale_positions(current_prices={"SOL": 110.0})

    assert fill.position_id in closed

    row = db.fetchone("SELECT status, realized_pnl FROM positions WHERE id = ?", (fill.position_id,))
    assert row is not None
    assert row[0] == "closed"
    assert row[1] is not None  # realized_pnl recorded


def test_expire_stale_positions_skips_fresh(temp_dir: Path) -> None:
    """expire_stale_positions does NOT close a recently opened position."""
    db = Database(temp_dir / "brain.db")
    cfg = Config.from_repo_defaults()
    object.__setattr__(cfg.execution, "mode", "paper")
    object.__setattr__(cfg.execution, "paper_max_hold_hours", 72)

    broker = PaperBroker(db)
    pnl = PnLTracker(db, config=cfg)

    fill = broker.execute_market(
        symbol="ETH",
        direction="short",
        notional_usd=500.0,
        leverage=1.0,
        mid_price=2000.0,
        idempotency_key="ts-2",
    )

    closed = pnl.expire_stale_positions(current_prices={"ETH": 1900.0})
    assert fill.position_id not in closed

    row = db.fetchone("SELECT status FROM positions WHERE id = ?", (fill.position_id,))
    assert row[0] == "open"


def test_paper_ignore_consecutive_loss_gate(temp_dir: Path) -> None:
    """KS-1 consecutive-loss escalation is suppressed in paper mode when flag is True."""
    db = Database(temp_dir / "brain.db")
    cfg = Config.from_repo_defaults()
    object.__setattr__(cfg.execution, "mode", "paper")
    object.__setattr__(cfg.execution, "paper_ignore_consecutive_loss_gate", True)

    broker = PaperBroker(db)
    pnl = PnLTracker(db, config=cfg)

    # Open and close 3 losing positions to trigger the gate
    for i in range(3):
        fill = broker.execute_market(
            symbol="SOL",
            direction="long",
            notional_usd=500.0,
            leverage=1.0,
            mid_price=100.0,
            idempotency_key=f"loss-gate-{i}",
        )
        pnl.close_position(position_id=fill.position_id, exit_price=50.0, reason="sl")
        # Clear the open position so next one can open (single-position broker)

    # Kill-switch should remain at level 0 (SAFE) — not escalated
    from engine.brain.kill_switch import KillSwitch

    ks = KillSwitch(cfg, db)
    assert ks.level == 0, f"Expected kill-switch level 0 (SAFE), got {ks.level}"
