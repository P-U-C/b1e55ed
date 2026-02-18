from __future__ import annotations

from pathlib import Path

from engine.core.database import Database
from engine.execution.paper import PaperBroker


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
