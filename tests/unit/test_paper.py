from __future__ import annotations

from pathlib import Path

import pytest

from engine.core.database import Database
from engine.execution.paper import PaperBroker, PaperConfig


def test_paper_exec_creates_order_and_position(temp_dir: Path) -> None:
    db = Database(temp_dir / "brain.db")
    broker = PaperBroker(db)

    fill = broker.execute_market(
        symbol="BTC",
        direction="long",
        notional_usd=1000.0,
        leverage=1.0,
        mid_price=50_000.0,
        idempotency_key="abc",
    )

    pos = db.conn.execute("SELECT * FROM positions WHERE id = ?", (fill.position_id,)).fetchone()
    assert pos is not None
    assert pos["asset"] == "BTC"
    assert pos["direction"] == "long"

    order = db.conn.execute("SELECT * FROM orders WHERE id = ?", (fill.order_id,)).fetchone()
    assert order is not None
    assert order["status"] == "filled"
    assert order["idempotency_key"] == "abc"


def test_paper_idempotency_key_returns_existing(temp_dir: Path) -> None:
    db = Database(temp_dir / "brain.db")
    broker = PaperBroker(db)

    a = broker.execute_market(
        symbol="ETH",
        direction="long",
        notional_usd=1000.0,
        leverage=1.0,
        mid_price=2000.0,
        idempotency_key="idem",
    )
    b = broker.execute_market(
        symbol="ETH",
        direction="long",
        notional_usd=1000.0,
        leverage=1.0,
        mid_price=2000.0,
        idempotency_key="idem",
    )

    assert a.order_id == b.order_id
    assert a.position_id == b.position_id


def test_paper_multi_position_same_symbol(temp_dir: Path) -> None:
    """paper_max_positions_per_symbol=2 allows a second concurrent position."""
    db = Database(temp_dir / "brain.db")
    cfg = PaperConfig(max_positions_per_symbol=2)
    broker = PaperBroker(db, config=cfg)

    fill1 = broker.execute_market(
        symbol="SOL",
        direction="long",
        notional_usd=500.0,
        leverage=1.0,
        mid_price=100.0,
        idempotency_key="sol-1",
    )
    # Second position on same symbol — must succeed
    fill2 = broker.execute_market(
        symbol="SOL",
        direction="short",
        notional_usd=500.0,
        leverage=1.0,
        mid_price=100.0,
        idempotency_key="sol-2",
    )

    assert fill1.position_id != fill2.position_id

    # Third position must be rejected (at limit=2)
    with pytest.raises(ValueError, match="duplicate_open_position"):
        broker.execute_market(
            symbol="SOL",
            direction="long",
            notional_usd=500.0,
            leverage=1.0,
            mid_price=100.0,
            idempotency_key="sol-3",
        )


def test_paper_same_direction_dedup_blocks_duplicate(temp_dir: Path) -> None:
    """Same symbol + same direction must be rejected even when max_positions_per_symbol=2."""
    db = Database(temp_dir / "brain.db")
    cfg = PaperConfig(max_positions_per_symbol=2)
    broker = PaperBroker(db, config=cfg)

    broker.execute_market(
        symbol="DOGE",
        direction="short",
        notional_usd=500.0,
        leverage=1.0,
        mid_price=0.15,
        idempotency_key="doge-short-1",
    )

    # Second short on same symbol must be rejected (direction-level dedup)
    with pytest.raises(ValueError, match="duplicate_open_position.*open short"):
        broker.execute_market(
            symbol="DOGE",
            direction="short",
            notional_usd=500.0,
            leverage=1.0,
            mid_price=0.15,
            idempotency_key="doge-short-2",
        )


def test_paper_conviction_flip_allowed(temp_dir: Path) -> None:
    """Opposite direction (conviction flip) must still be allowed."""
    db = Database(temp_dir / "brain.db")
    cfg = PaperConfig(max_positions_per_symbol=2)
    broker = PaperBroker(db, config=cfg)

    fill1 = broker.execute_market(
        symbol="BTC",
        direction="long",
        notional_usd=1000.0,
        leverage=1.0,
        mid_price=50_000.0,
        idempotency_key="btc-long-1",
    )

    # Short on same symbol must succeed (different direction)
    fill2 = broker.execute_market(
        symbol="BTC",
        direction="short",
        notional_usd=1000.0,
        leverage=1.0,
        mid_price=50_000.0,
        idempotency_key="btc-short-1",
    )

    assert fill1.position_id != fill2.position_id


def test_paper_single_position_legacy_blocks_duplicate(temp_dir: Path) -> None:
    """max_positions_per_symbol=1 (legacy default) still blocks a second position."""
    db = Database(temp_dir / "brain.db")
    broker = PaperBroker(db)  # default PaperConfig: max_positions_per_symbol=1

    broker.execute_market(
        symbol="BTC",
        direction="long",
        notional_usd=1000.0,
        leverage=1.0,
        mid_price=50_000.0,
        idempotency_key="btc-1",
    )

    with pytest.raises(ValueError, match="duplicate_open_position"):
        broker.execute_market(
            symbol="BTC",
            direction="short",
            notional_usd=1000.0,
            leverage=1.0,
            mid_price=50_000.0,
            idempotency_key="btc-2",
        )
