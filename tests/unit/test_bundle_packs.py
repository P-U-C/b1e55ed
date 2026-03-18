from __future__ import annotations

from engine.core.bundle_packs import bundle_template_from_pack, get_bundle_pack, list_bundle_packs


def test_required_tradfi_and_hl_pack_ids_present() -> None:
    pack_ids = {p["id"] for p in list_bundle_packs()}
    assert {"tradfi-infra", "hl-tradfi-perps", "mixed-market"}.issubset(pack_ids)


def test_pack_symbol_sets_match_expected_initial_coverage() -> None:
    tradfi = get_bundle_pack("tradfi-infra")
    hl = get_bundle_pack("hl-tradfi-perps")
    mixed = get_bundle_pack("mixed-market")

    assert tradfi is not None
    assert hl is not None
    assert mixed is not None

    # tradfi-infra: TradFi equities and ETFs
    assert tradfi["symbols"] == ["SPY", "QQQ", "GLD", "TLT", "USO", "IWM", "DIA", "XLF", "XLE", "XLK"]
    # hl-tradfi-perps: Hyperliquid TradFi perps (US tech, mag7, high-vol stocks)
    assert hl["symbols"] == ["AAPL", "TSLA", "NVDA", "AMZN", "GOOGL", "META", "MSFT", "NFLX", "AMD", "COIN", "MSTR", "PLTR"]
    # mixed-market: Cross-market crypto + macro ETFs + crypto-adjacent equities
    assert mixed["symbols"] == ["BTC", "ETH", "SOL", "SPY", "QQQ", "GLD", "TLT", "NVDA", "COIN", "MSTR"]


def test_hl_pack_contains_proxy_mapping_metadata_and_factor_tags() -> None:
    pack = get_bundle_pack("hl-tradfi-perps")
    assert pack is not None

    # COIN is a crypto-proxy equity on Hyperliquid
    coin = pack["mappings"]["COIN"]
    assert coin["mapping"] == "proxy"
    assert coin["confidence"] == "medium"
    assert coin["proxy_symbol"] == "BTC"
    assert {"vol", "beta"}.issubset(set(coin["factors"]))

    assert pack["mapping_summary"]["proxy"] >= 1
    assert {"rates", "vol", "beta"}.issubset(set(pack["factor_tags"]))


def test_bundle_template_from_pack_includes_pack_tag_and_defaults() -> None:
    template = bundle_template_from_pack("tradfi-infra", source="wizard")
    assert template is not None

    assert template["id"] == "tradfi-infra"
    assert template["asset_class"] == "tradfi"
    assert template["venue"] == "yfinance"
    assert "pack:tradfi-infra" in template["tags"]
