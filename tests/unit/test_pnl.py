from __future__ import annotations

from pathlib import Path

import pytest

from engine.core.database import Database
from engine.execution.paper import PaperBroker
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
