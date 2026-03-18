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
}


def fetch_price_usd(symbol: str, timeout_sec: int = 5) -> float | None:
    """Fetch current USD price for a symbol via Binance (primary) or CoinGecko (fallback).

    Returns None on failure — callers should handle gracefully.
    """
    sym = symbol.upper().replace("-USD", "").replace("USDT", "")

    # Try Binance first — no rate limits for single spot queries.
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={sym}USDT"
        with urllib.request.urlopen(url, timeout=timeout_sec) as resp:  # noqa: S310
            data = json.loads(resp.read())
            return float(data["price"])
    except Exception:  # noqa: BLE001
        pass

    # Fallback: CoinGecko simple price endpoint.
    cg_id = COINGECKO_SYMBOL_MAP.get(sym)
    if not cg_id:
        return None
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd"
        with urllib.request.urlopen(url, timeout=timeout_sec) as resp:  # noqa: S310
            data = json.loads(resp.read())
            return float(data[cg_id]["usd"])
    except Exception:  # noqa: BLE001
        return None
