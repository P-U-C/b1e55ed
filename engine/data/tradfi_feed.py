"""TradFi price feed with yfinance primary and Twelve Data fallback.

Usage::

    feed = TradFiFeed()
    candles = feed.get_ohlcv("SPY", interval="1h", bars=200)
    # returns list of {"timestamp": int, "open": float, "high": float,
    #                   "low": float, "close": float, "volume": float}

Environment variables:
    B1E55ED_TWELVEDATA_KEY  — optional Twelve Data API key; enables fallback.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_UNSET = object()

# yfinance period map: interval → history period
_YF_PERIOD_MAP: dict[str, str] = {
    "1m": "7d",
    "5m": "60d",
    "15m": "60d",
    "1h": "730d",
    "4h": "730d",
    "1d": "max",
}


class TradFiFeed:
    """Fetch OHLCV data for equities and ETFs (TradFi symbols not on Binance).

    Primary source: yfinance (no API key required).
    Fallback: Twelve Data (requires ``B1E55ED_TWELVEDATA_KEY`` env var or
    explicit ``twelvedata_key`` constructor argument).
    """

    def __init__(self, twelvedata_key: str | None = _UNSET) -> None:
        if twelvedata_key is _UNSET:
            twelvedata_key = os.environ.get("B1E55ED_TWELVEDATA_KEY") or None
        self._td_key: str | None = twelvedata_key

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_ohlcv(
        self,
        symbol: str,
        *,
        interval: str = "1h",
        bars: int = 200,
    ) -> list[dict[str, Any]]:
        """Return the last *bars* OHLCV candles for *symbol*.

        Each candle is a dict with keys:
        ``timestamp`` (Unix ms int), ``open``, ``high``, ``low``, ``close``,
        ``volume`` (all floats).

        Raises:
            RuntimeError: if both yfinance and Twelve Data fail / are unavailable.
        """
        # --- Primary: yfinance ---
        try:
            data = self._fetch_yfinance(symbol, interval=interval, bars=bars)
            if data:
                return data
            # empty DataFrame → fall through to Twelve Data
        except Exception as exc:  # noqa: BLE001
            logger.debug("tradfi_feed yfinance failed symbol=%s error=%s", symbol, exc)

        # --- Fallback: Twelve Data ---
        if not self._td_key:
            raise RuntimeError(f"TradFiFeed: yfinance returned no data for {symbol} and B1E55ED_TWELVEDATA_KEY is not set — cannot fall back to Twelve Data.")
        return self._fetch_twelvedata(symbol, interval=interval, bars=bars)

    def get_current_price(self, symbol: str) -> float:
        """Return the most recent close price for *symbol*."""
        candles = self.get_ohlcv(symbol, interval="1h", bars=5)
        return float(candles[-1]["close"])

    def is_available(self) -> bool:
        """Return True if at least one data source is reachable for a test symbol."""
        try:
            self.get_ohlcv("SPY", interval="1h", bars=5)
            return True
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_yfinance(
        self,
        symbol: str,
        *,
        interval: str,
        bars: int,
    ) -> list[dict[str, Any]]:
        import yfinance as yf  # lazy import

        period = _YF_PERIOD_MAP.get(interval, "730d")
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval, auto_adjust=True)
        if df is None or df.empty:
            return []

        df = df.iloc[-bars:]

        result: list[dict[str, Any]] = []
        for ts, row in df.iterrows():
            result.append(
                {
                    "timestamp": int(ts.timestamp() * 1000),
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": float(row["Volume"]),
                }
            )
        return result

    def _fetch_twelvedata(
        self,
        symbol: str,
        *,
        interval: str,
        bars: int,
    ) -> list[dict[str, Any]]:
        import twelvedata  # lazy import

        client = twelvedata.TDClient(apikey=self._td_key)
        ts = client.time_series(
            symbol=symbol,
            interval=interval,
            outputsize=bars,
        )
        df = ts.as_pandas()
        if df is None or df.empty:
            raise RuntimeError(f"TradFiFeed: Twelve Data returned empty data for {symbol}")

        # Twelve Data returns newest-first — reverse to chronological
        df = df.iloc[::-1]

        result: list[dict[str, Any]] = []
        for ts_idx, row in df.iterrows():
            result.append(
                {
                    "timestamp": int(ts_idx.timestamp() * 1000),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                }
            )
        return result[-bars:]
