from __future__ import annotations

from engine.execution.hyperliquid import HyperliquidAdapter, InMemoryHyperliquidApi


def test_place_and_fill_and_cancel() -> None:
    api = InMemoryHyperliquidApi()
    hl = HyperliquidAdapter(api=api)

    o = hl.place(symbol="HYPE", side="buy", size=1.25, price=10.0)
    assert o.status == "open"

    filled = api.fill_order(order_id=o.id, fill_price=10.1)
    assert filled.status == "filled"
    assert filled.filled_price == 10.1

    # cannot cancel filled
    assert hl.cancel(order_id=o.id) is False

    # place another order and cancel
    o2 = hl.place(symbol="HYPE", side="sell", size=0.5, price=10.2)
    assert hl.cancel(order_id=o2.id) is True
    assert hl.status(order_id=o2.id) is not None
    assert hl.status(order_id=o2.id).status == "canceled"
