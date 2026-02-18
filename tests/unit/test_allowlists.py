from __future__ import annotations

from engine.core.allowlists import Allowlists


def test_allowlists_enforcement() -> None:
    a = Allowlists(
        venues=frozenset({"hyperliquid"}),
        chains=frozenset({"solana"}),
        tokens=frozenset({"BTC"}),
    )

    assert a.venue_allowed("hyperliquid")
    assert not a.venue_allowed("binance")

    assert a.chain_allowed("solana")
    assert a.chain_allowed("SoLaNa")
    assert not a.chain_allowed("ethereum")

    assert a.token_allowed("BTC")
    assert a.token_allowed("btc")
    assert not a.token_allowed("ETH")
