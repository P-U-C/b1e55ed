"""engine.core.bundle_packs

Data-driven runtime universe bundle packs.

A pack bundles symbols plus lightweight mapping metadata:
- direct mapping: symbol has first-order coverage from the producer stack
- proxy mapping: symbol is inferred from a mapped proxy symbol/factor basket
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

_ALLOWED_MAPPING_TYPES = {"direct", "proxy"}
_ALLOWED_CONFIDENCE = {"high", "medium", "low"}
_ALLOWED_SOURCES = {"wizard", "user", "system"}

_BUNDLE_PACKS_RAW: dict[str, dict[str, Any]] = {
    "crypto-core": {
        "id": "crypto-core",
        "name": "Crypto Core",
        "description": "Default liquid crypto symbols with direct coverage.",
        "symbols": ["BTC", "ETH", "SOL"],
        "tags": ["starter", "crypto", "core"],
        "asset_class": "crypto",
        "venue": "global",
        "mappings": {
            "BTC": {
                "mapping": "direct",
                "confidence": "high",
                "factors": ["rates", "dollar", "liquidity", "beta"],
            },
            "ETH": {
                "mapping": "direct",
                "confidence": "high",
                "factors": ["rates", "dollar", "liquidity", "beta"],
            },
            "SOL": {
                "mapping": "direct",
                "confidence": "medium",
                "factors": ["beta", "vol", "liquidity"],
            },
        },
    },
    "tradfi-infra": {
        "id": "tradfi-infra",
        "name": "TradFi Infra",
        "description": "TradFi equities and ETFs (SPY, QQQ, GLD, TLT, USO) via yfinance. Add to tradfi_symbols in settings.",
        "symbols": ["SPY", "QQQ", "GLD", "TLT", "USO", "IWM", "DIA", "XLF", "XLE", "XLK"],
        "tags": ["starter", "tradfi", "infra", "carry", "basis", "equities", "etf"],
        "asset_class": "tradfi",
        "venue": "yfinance",
        "mappings": {
            "SPY": {
                "mapping": "direct",
                "confidence": "high",
                "factors": ["rates", "dollar", "liquidity", "beta"],
                "note": "S&P 500 ETF — broad US equity beta.",
            },
            "QQQ": {
                "mapping": "direct",
                "confidence": "high",
                "factors": ["rates", "beta", "liquidity"],
                "note": "Nasdaq 100 ETF — tech/growth beta.",
            },
            "GLD": {
                "mapping": "direct",
                "confidence": "high",
                "factors": ["dollar", "rates", "vol"],
                "note": "Gold ETF — safe haven / dollar inverse.",
            },
            "TLT": {
                "mapping": "direct",
                "confidence": "high",
                "factors": ["rates", "dollar"],
                "note": "20Y Treasury ETF — rates duration.",
            },
            "USO": {
                "mapping": "direct",
                "confidence": "medium",
                "factors": ["dollar", "liquidity"],
                "note": "Oil ETF — commodity / inflation proxy.",
            },
            "IWM": {
                "mapping": "direct",
                "confidence": "medium",
                "factors": ["beta", "liquidity"],
                "note": "Russell 2000 ETF — small cap risk.",
            },
            "DIA": {
                "mapping": "proxy",
                "confidence": "medium",
                "proxy_symbol": "SPY",
                "factors": ["beta", "liquidity"],
                "note": "Dow Jones ETF — proxy to SPY.",
            },
            "XLF": {
                "mapping": "direct",
                "confidence": "medium",
                "factors": ["rates", "beta"],
                "note": "Financials sector ETF — rates sensitive.",
            },
            "XLE": {
                "mapping": "direct",
                "confidence": "medium",
                "factors": ["dollar", "liquidity"],
                "note": "Energy sector ETF.",
            },
            "XLK": {
                "mapping": "direct",
                "confidence": "medium",
                "factors": ["beta", "rates"],
                "note": "Tech sector ETF.",
            },
        },
    },
    "hl-tradfi-perps": {
        "id": "hl-tradfi-perps",
        "name": "Hyperliquid TradFi-Perps",
        "description": "Hyperliquid perp basket — majors + high-beta alts with TradFi factor overlays.",
        "symbols": ["BTC", "ETH", "SOL", "HYPE", "SUI", "AVAX", "LINK", "ARB", "OP", "DOGE"],
        "tags": ["starter", "hyperliquid", "tradfi", "perps", "beta"],
        "asset_class": "crypto",
        "venue": "hyperliquid",
        "mappings": {
            "BTC": {
                "mapping": "direct",
                "confidence": "high",
                "factors": ["rates", "dollar", "liquidity"],
            },
            "ETH": {
                "mapping": "direct",
                "confidence": "high",
                "factors": ["rates", "dollar", "beta", "liquidity"],
            },
            "SOL": {
                "mapping": "direct",
                "confidence": "high",
                "factors": ["beta", "vol", "liquidity"],
            },
            "HYPE": {
                "mapping": "proxy",
                "confidence": "medium",
                "proxy_symbol": "SOL",
                "factors": ["vol", "beta", "liquidity"],
                "note": "HL native token — uses SOL/BTC macro proxies.",
            },
            "SUI": {
                "mapping": "proxy",
                "confidence": "medium",
                "proxy_symbol": "SOL",
                "factors": ["beta", "liquidity"],
            },
            "AVAX": {
                "mapping": "direct",
                "confidence": "medium",
                "factors": ["beta", "liquidity"],
            },
            "LINK": {
                "mapping": "direct",
                "confidence": "medium",
                "factors": ["beta", "vol"],
            },
            "ARB": {
                "mapping": "proxy",
                "confidence": "low",
                "proxy_symbol": "ETH",
                "factors": ["beta", "liquidity"],
            },
            "OP": {
                "mapping": "proxy",
                "confidence": "low",
                "proxy_symbol": "ETH",
                "factors": ["beta", "liquidity"],
            },
            "DOGE": {
                "mapping": "direct",
                "confidence": "low",
                "factors": ["beta", "vol"],
            },
        },
    },
    "mixed-market": {
        "id": "mixed-market",
        "name": "Mixed Market",
        "description": "Balanced cross-market starter: direct majors + proxy extensions.",
        "symbols": ["BTC", "ETH", "SOL", "HYPE", "SUI"],
        "tags": ["starter", "mixed", "cross-market"],
        "asset_class": "mixed",
        "venue": "global",
        "mappings": {
            "BTC": {
                "mapping": "direct",
                "confidence": "high",
                "factors": ["rates", "dollar", "liquidity"],
            },
            "ETH": {
                "mapping": "direct",
                "confidence": "high",
                "factors": ["rates", "dollar", "beta", "liquidity"],
            },
            "SOL": {
                "mapping": "direct",
                "confidence": "medium",
                "factors": ["beta", "vol", "liquidity"],
            },
            "HYPE": {
                "mapping": "proxy",
                "confidence": "medium",
                "proxy_symbol": "SOL",
                "factors": ["vol", "beta", "liquidity"],
            },
            "SUI": {
                "mapping": "proxy",
                "confidence": "low",
                "proxy_symbol": "SOL",
                "factors": ["beta", "liquidity"],
            },
        },
    },
}


def _normalize_symbols(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        sym = str(raw or "").strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    return out


def _normalize_tags(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        tag = str(raw or "").strip().lower()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out


def _normalize_mapping(symbol: str, raw: dict[str, Any]) -> dict[str, Any]:
    mapping = str(raw.get("mapping") or "direct").strip().lower()
    if mapping not in _ALLOWED_MAPPING_TYPES:
        mapping = "direct"

    confidence = str(raw.get("confidence") or "medium").strip().lower()
    if confidence not in _ALLOWED_CONFIDENCE:
        confidence = "medium"

    factors = _normalize_tags(raw.get("factors") if isinstance(raw.get("factors"), list) else [])

    proxy_symbol = str(raw.get("proxy_symbol") or "").strip().upper() or None
    note = str(raw.get("note") or "").strip() or None

    normalized: dict[str, Any] = {
        "symbol": symbol,
        "mapping": mapping,
        "confidence": confidence,
        "factors": factors,
    }
    if proxy_symbol:
        normalized["proxy_symbol"] = proxy_symbol
    if note:
        normalized["note"] = note
    return normalized


def _normalize_pack(raw_pack: dict[str, Any]) -> dict[str, Any]:
    pack = deepcopy(raw_pack)

    pack_id = str(pack.get("id") or "").strip().lower()
    if not pack_id:
        raise ValueError("Bundle pack id is required")

    name = str(pack.get("name") or pack_id).strip() or pack_id
    description = str(pack.get("description") or "").strip()

    raw_mappings_obj = pack.get("mappings")
    raw_mappings: dict[str, Any] = raw_mappings_obj if isinstance(raw_mappings_obj, dict) else {}

    raw_symbols_obj = pack.get("symbols")
    raw_symbols: list[str] = raw_symbols_obj if isinstance(raw_symbols_obj, list) else list(raw_mappings.keys())
    symbols = _normalize_symbols(raw_symbols)

    for key in raw_mappings:
        sym = str(key or "").strip().upper()
        if sym and sym not in symbols:
            symbols.append(sym)

    mappings: dict[str, dict[str, Any]] = {}
    factor_tags: set[str] = set()
    direct_count = 0
    proxy_count = 0

    for symbol in symbols:
        raw_meta = raw_mappings.get(symbol, {})
        raw_meta = raw_meta if isinstance(raw_meta, dict) else {}
        meta = _normalize_mapping(symbol, raw_meta)
        mappings[symbol] = meta
        factor_tags.update(meta.get("factors") or [])
        if meta.get("mapping") == "proxy":
            proxy_count += 1
        else:
            direct_count += 1

    raw_tags = pack.get("tags") if isinstance(pack.get("tags"), list) else []
    tags = _normalize_tags([*raw_tags, *sorted(factor_tags), f"pack:{pack_id}"])

    asset_class = str(pack.get("asset_class") or "crypto").strip().lower() or "crypto"
    venue = str(pack.get("venue") or "global").strip().lower() or "global"

    return {
        "id": pack_id,
        "name": name,
        "description": description,
        "symbols": symbols,
        "tags": tags,
        "asset_class": asset_class,
        "venue": venue,
        "factor_tags": sorted(factor_tags),
        "mapping_summary": {"direct": direct_count, "proxy": proxy_count},
        "mappings": mappings,
    }


def list_bundle_packs() -> list[dict[str, Any]]:
    """Return normalized runtime bundle packs sorted by id."""
    packs = [_normalize_pack(v) for v in _BUNDLE_PACKS_RAW.values()]
    return sorted(packs, key=lambda p: str(p.get("id") or ""))


def get_bundle_pack(pack_id: str) -> dict[str, Any] | None:
    """Return a single normalized bundle pack by id."""
    pid = str(pack_id or "").strip().lower()
    if not pid:
        return None
    raw = _BUNDLE_PACKS_RAW.get(pid)
    if raw is None:
        return None
    return _normalize_pack(raw)


def bundle_template_from_pack(
    pack_id: str,
    *,
    source: str = "system",
    enabled: bool = True,
    name: str | None = None,
    symbols: list[str] | None = None,
    tags: list[str] | None = None,
    asset_class: str | None = None,
    venue: str | None = None,
) -> dict[str, Any] | None:
    """Build a UniverseBundle-compatible template from a pack definition."""
    pack = get_bundle_pack(pack_id)
    if pack is None:
        return None

    final_symbols = _normalize_symbols(symbols if symbols else list(pack.get("symbols") or []))
    base_tags = list(pack.get("tags") or [])
    extra_tags = tags if isinstance(tags, list) else []
    final_tags = _normalize_tags([*base_tags, *extra_tags])

    source_value = str(source or "system").strip().lower()
    if source_value not in _ALLOWED_SOURCES:
        source_value = "system"

    name_value = str(name or "").strip() or str(pack.get("name") or pack.get("id") or "Bundle")
    asset_class_value = str(asset_class or "").strip().lower() or str(pack.get("asset_class") or "crypto")
    venue_value = str(venue or "").strip().lower() or str(pack.get("venue") or "global")

    return {
        "id": str(pack.get("id")),
        "name": name_value,
        "symbols": final_symbols,
        "tags": final_tags,
        "asset_class": asset_class_value,
        "venue": venue_value,
        "enabled": bool(enabled),
        "source": source_value,
    }
