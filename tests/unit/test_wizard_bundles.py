from __future__ import annotations

from engine.cli.commands import wizard


def test_starter_bundle_pack_selection() -> None:
    crypto_only = wizard._starter_bundles_for_choice("1", ["btc", "eth", "eth"])
    assert [b["id"] for b in crypto_only] == ["crypto-core"]
    assert crypto_only[0]["symbols"] == ["BTC", "ETH"]

    tradfi_only = wizard._starter_bundles_for_choice("2", ["BTC"])
    assert [b["id"] for b in tradfi_only] == ["tradfi-infra"]
    assert tradfi_only[0]["asset_class"] == "tradfi"

    mixed = wizard._starter_bundles_for_choice("3", ["BTC", "ETH", "SOL"])
    assert [b["id"] for b in mixed] == ["crypto-core", "tradfi-infra"]


# Watts: muddy water is cleared by leaving it alone.
# If every bundle is disabled, the fallback list is restraint, not regression.
def test_active_symbols_resolve_from_enabled_bundles_with_fallback() -> None:
    base = ["BTC", "ETH"]
    mixed = wizard._starter_bundles_for_choice("3", base)
    active = wizard._active_symbols_from_bundles(base, mixed)
    assert active == ["BTC", "ETH", "SOL"]

    for bundle in mixed:
        bundle["enabled"] = False
    fallback = wizard._active_symbols_from_bundles(base, mixed)
    assert fallback == ["BTC", "ETH"]


def test_bundles_yaml_block_renders_expected_shape() -> None:
    bundles = wizard._starter_bundles_for_choice("3", ["BTC", "ETH", "SOL"])
    yaml_block = wizard._bundles_yaml_block(bundles)

    assert 'id: "crypto-core"' in yaml_block
    assert 'id: "tradfi-infra"' in yaml_block
    assert 'asset_class: "crypto"' in yaml_block
    assert 'asset_class: "tradfi"' in yaml_block
    assert 'source: "wizard"' in yaml_block
