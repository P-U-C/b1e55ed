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

    assert tradfi["symbols"] == ["BTC", "ETH", "SOL"]
    assert hl["symbols"] == ["HYPE", "SOL", "BTC", "ETH"]
    assert mixed["symbols"] == ["BTC", "ETH", "SOL", "HYPE", "SUI"]


# Popper in test form: proxy mapping is a claim that must survive contact with fixtures.
def test_hl_pack_contains_proxy_mapping_metadata_and_factor_tags() -> None:
    pack = get_bundle_pack("hl-tradfi-perps")
    assert pack is not None

    hype = pack["mappings"]["HYPE"]
    assert hype["mapping"] == "proxy"
    assert hype["confidence"] == "medium"
    assert hype["proxy_symbol"] == "SOL"
    assert {"vol", "beta", "liquidity"}.issubset(set(hype["factors"]))

    assert pack["mapping_summary"]["proxy"] >= 1
    assert {"rates", "dollar", "vol", "beta", "liquidity"}.issubset(set(pack["factor_tags"]))


def test_bundle_template_from_pack_includes_pack_tag_and_defaults() -> None:
    template = bundle_template_from_pack("tradfi-infra", source="wizard")
    assert template is not None

    assert template["id"] == "tradfi-infra"
    assert template["asset_class"] == "tradfi"
    assert template["venue"] == "binance"
    assert "pack:tradfi-infra" in template["tags"]
