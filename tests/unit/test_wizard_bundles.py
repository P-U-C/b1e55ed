from __future__ import annotations

from engine.cli.commands import wizard


def test_starter_bundle_pack_selection() -> None:
    crypto_only = wizard._starter_bundles_for_choice("1", ["btc", "eth", "eth"])
    assert [b["id"] for b in crypto_only] == ["crypto-core"]
    assert crypto_only[0]["symbols"] == ["BTC", "ETH"]

    tradfi_only = wizard._starter_bundles_for_choice("2", ["BTC"])
    assert [b["id"] for b in tradfi_only] == ["tradfi-infra"]
    assert tradfi_only[0]["asset_class"] == "tradfi"

    hl_pack = wizard._starter_bundles_for_choice("3", ["BTC", "ETH", "SOL"])
    assert [b["id"] for b in hl_pack] == ["hl-tradfi-perps"]
    assert hl_pack[0]["venue"] == "hyperliquid"

    mixed_pack = wizard._starter_bundles_for_choice("4", ["BTC", "ETH", "SOL"])
    assert [b["id"] for b in mixed_pack] == ["mixed-market"]
    assert "NVDA" in mixed_pack[0]["symbols"]


def test_active_symbols_resolve_from_enabled_bundles_with_fallback() -> None:
    base = ["BTC", "ETH"]
    hl = wizard._starter_bundles_for_choice("3", base)
    active = wizard._active_symbols_from_bundles(base, hl)
    assert active == ["AAPL", "TSLA", "NVDA", "AMZN", "GOOGL", "META", "MSFT", "NFLX", "AMD", "COIN", "MSTR", "PLTR"]

    for bundle in hl:
        bundle["enabled"] = False
    fallback = wizard._active_symbols_from_bundles(base, hl)
    assert fallback == ["BTC", "ETH"]


def test_bundles_yaml_block_renders_expected_shape() -> None:
    bundles = wizard._starter_bundles_for_choice("3", ["BTC", "ETH", "SOL"])
    yaml_block = wizard._bundles_yaml_block(bundles)

    assert 'id: "hl-tradfi-perps"' in yaml_block
    assert 'asset_class: "tradfi"' in yaml_block
    assert 'venue: "hyperliquid"' in yaml_block
    assert 'source: "wizard"' in yaml_block
