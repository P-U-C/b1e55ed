"""Price feed for SPI signal resolution."""

from __future__ import annotations

import json
import urllib.request

COINGECKO_SYMBOL_MAP: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "SUI": "sui",
    "HYPE": "hyperliquid",
    "XRP": "ripple",
    "DOT": "polkadot",
    "UNI": "uniswap",
    "LTC": "litecoin",
    "ATOM": "cosmos",
    "NEAR": "near",
    "ARB": "arbitrum",
    "OP": "optimism",
    "MATIC": "matic-network",
    "FIL": "filecoin",
    "AAVE": "aave",
    "CRV": "curve-dao-token",
    "SNX": "havven",
    "APT": "aptos",
    "INJ": "injective-protocol",
    "TIA": "celestia",
    "SEI": "sei-network",
    "JTO": "jito-governance-token",
    "WIF": "dogwifcoin",
    "BONK": "bonk",
    "JUP": "jupiter-exchange-solana",
    "PYTH": "pyth-network",
    "PEPE": "pepe",
    "FLOKI": "floki",
    "RENDER": "render-token",
    "FET": "fetch-ai",
    "OCEAN": "ocean-protocol",
    "TAO": "bittensor",
    "VIRTUAL": "virtual-protocol",
    "AI16Z": "ai16z",
    "AIXBT": "aixbt-by-virtuals",
}

# Kraken symbol overrides (most major pairs supported)
KRAKEN_SYMBOL_MAP: dict[str, str] = {
    "BTC": "XBTUSD",
    "ETH": "ETHUSD",
    "SOL": "SOLUSD",
    "ADA": "ADAUSD",
    "DOGE": "XDGUSD",
    "DOT": "DOTUSD",
    "LINK": "LINKUSD",
    "UNI": "UNIUSD",
    "ATOM": "ATOMUSD",
    "NEAR": "NEARUSD",
    "MATIC": "MATICUSD",
    "AVAX": "AVAXUSD",
    "AAVE": "AAVEUSD",
    "LTC": "XLTCZUSD",
    "FIL": "FILUSD",
    "APT": "APTUSD",
    "INJ": "INJUSD",
    "PEPE": "PEPEUSD",
    "FET": "FETUSD",
    "RENDER": "RENDERUSD",
    "ARB": "ARBUSD",
    "OP": "OPUSD",
    "TIA": "TIAUSD",
    "WIF": "WIFUSD",
    "BONK": "BONKUSD",
    "JUP": "JUPUSD",
}


def _try_coingecko_with_map(sym: str, timeout_sec: int, cg_map: dict[str, str]) -> float | None:
    cg_id = cg_map.get(sym)
    if not cg_id:
        return None
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd"
        with urllib.request.urlopen(url, timeout=timeout_sec) as resp:  # noqa: S310
            data = json.loads(resp.read())
            return float(data[cg_id]["usd"])
    except Exception:  # noqa: BLE001
        return None


def _try_kraken_with_map(sym: str, timeout_sec: int, kr_map: dict[str, str]) -> float | None:
    kraken_pair = kr_map.get(sym)
    if not kraken_pair:
        return None
    try:
        url = f"https://api.kraken.com/0/public/Ticker?pair={kraken_pair}"
        with urllib.request.urlopen(url, timeout=timeout_sec) as resp:  # noqa: S310
            data = json.loads(resp.read())
            result = data.get("result", {})
            if result:
                pair_data = next(iter(result.values()))
                return float(pair_data["c"][0])  # last trade close price
    except Exception:  # noqa: BLE001
        pass
    return None


# Convenience aliases using static maps (used by tests and simple callers).
def _try_coingecko(sym: str, timeout_sec: int) -> float | None:
    return _try_coingecko_with_map(sym, timeout_sec, COINGECKO_SYMBOL_MAP)


def _try_kraken(sym: str, timeout_sec: int) -> float | None:
    return _try_kraken_with_map(sym, timeout_sec, KRAKEN_SYMBOL_MAP)


def _try_yahoo(sym: str, timeout_sec: int) -> float | None:
    """Fetch equity price from Yahoo Finance (unofficial API).

    Works for stocks, ETFs, indices. Used as fallback when crypto feeds fail
    and as primary source for equity symbols (NVDA, AMD, etc).
    """
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1m&range=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:  # noqa: S310
            data = json.loads(resp.read())
            return float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])
    except Exception:  # noqa: BLE001
        return None


def _try_binance(sym: str, timeout_sec: int) -> float | None:
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={sym}USDT"
        with urllib.request.urlopen(url, timeout=timeout_sec) as resp:  # noqa: S310
            data = json.loads(resp.read())
            return float(data["price"])
    except Exception:  # noqa: BLE001
        return None


def fetch_price_usd(
    symbol: str,
    timeout_sec: int = 5,
    extra_coingecko: dict[str, str] | None = None,
    extra_kraken: dict[str, str] | None = None,
) -> float | None:
    """Fetch current USD price for a symbol.

    Provider order: CoinGecko → Kraken → Yahoo Finance → Binance.
    Binance is geo-blocked (HTTP 451) on some oracle deployments.

    Args:
        symbol: Ticker symbol (BTC, ETH, NVDA, etc.)
        timeout_sec: Per-request timeout in seconds.
        extra_coingecko: Additional symbol→CoinGecko-ID mappings (from config).
        extra_kraken: Additional symbol→Kraken-pair mappings (from config).

    Returns None on failure — callers should handle gracefully.
    """
    sym = symbol.upper().replace("-USD", "").replace("USDT", "")

    # Merge static maps with runtime config overrides.
    cg_map = {**COINGECKO_SYMBOL_MAP, **(extra_coingecko or {})}
    kr_map = {**KRAKEN_SYMBOL_MAP, **(extra_kraken or {})}

    price = _try_coingecko_with_map(sym, timeout_sec, cg_map)
    if price is not None:
        return price

    price = _try_kraken_with_map(sym, timeout_sec, kr_map)
    if price is not None:
        return price

    # Yahoo Finance handles equities (NVDA, AMD, etc) + broad crypto.
    price = _try_yahoo(sym, timeout_sec)
    if price is not None:
        return price

    # Last resort — may be geo-blocked.
    return _try_binance(sym, timeout_sec)
