"""Unit tests for engine.data.tradfi_feed.TradFiFeed.

Tests use monkeypatching to avoid real network calls.
"""

from __future__ import annotations

from datetime import UTC
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from engine.data.tradfi_feed import TradFiFeed

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ohlcv_df(n: int = 60) -> pd.DataFrame:
    """Build a minimal yfinance-style DataFrame."""
    from datetime import datetime, timedelta

    dates = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(n)]
    idx = pd.DatetimeIndex(dates)
    data = {
        "Open": [100.0 + i * 0.1 for i in range(n)],
        "High": [101.0 + i * 0.1 for i in range(n)],
        "Low": [99.0 + i * 0.1 for i in range(n)],
        "Close": [100.5 + i * 0.1 for i in range(n)],
        "Volume": [1_000_000 + i * 100 for i in range(n)],
    }
    return pd.DataFrame(data, index=idx)


def _make_td_df(n: int = 60) -> pd.DataFrame:
    """Build a minimal twelvedata-style DataFrame (newest first)."""
    from datetime import datetime, timedelta

    dates = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(n)]
    # Twelve Data returns newest first — reverse the list
    dates = list(reversed(dates))
    idx = pd.DatetimeIndex(dates)
    data = {
        "open": [str(100.0 + i * 0.1) for i in range(n)],
        "high": [str(101.0 + i * 0.1) for i in range(n)],
        "low": [str(99.0 + i * 0.1) for i in range(n)],
        "close": [str(100.5 + i * 0.1) for i in range(n)],
        "volume": [str(1_000_000 + i * 100) for i in range(n)],
    }
    return pd.DataFrame(data, index=idx)


# ---------------------------------------------------------------------------
# Test: yfinance primary — happy path
# ---------------------------------------------------------------------------


def test_get_ohlcv_yfinance_primary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Primary (yfinance) works → returns correct OHLCV format."""
    mock_df = _make_ohlcv_df(60)

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = mock_df

    with patch("yfinance.Ticker", return_value=mock_ticker):
        feed = TradFiFeed()
        result = feed.get_ohlcv("SPY", interval="1h", bars=60)

    assert isinstance(result, list)
    assert len(result) == 60
    first = result[0]
    assert set(first.keys()) == {"timestamp", "open", "high", "low", "close", "volume"}
    assert isinstance(first["close"], float)
    assert isinstance(first["timestamp"], int)
    assert first["close"] > 0


def test_get_ohlcv_trims_to_bars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the last *bars* candles are returned even if yfinance gave more."""
    mock_df = _make_ohlcv_df(120)
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = mock_df

    with patch("yfinance.Ticker", return_value=mock_ticker):
        feed = TradFiFeed()
        result = feed.get_ohlcv("SPY", interval="1h", bars=50)

    assert len(result) == 50


def test_get_current_price(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_current_price returns the latest close."""
    mock_df = _make_ohlcv_df(10)
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = mock_df

    with patch("yfinance.Ticker", return_value=mock_ticker):
        feed = TradFiFeed()
        price = feed.get_current_price("SPY")

    assert isinstance(price, float)
    assert price > 0


# ---------------------------------------------------------------------------
# Test: fallback fires when yfinance raises
# ---------------------------------------------------------------------------


def test_fallback_to_twelvedata_on_yfinance_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """When yfinance raises, TradFiFeed falls back to Twelve Data."""
    mock_td_df = _make_td_df(60)

    mock_ticker = MagicMock()
    mock_ticker.history.side_effect = RuntimeError("network error")

    mock_ts = MagicMock()
    mock_ts.as_pandas.return_value = mock_td_df
    mock_td_client = MagicMock()
    mock_td_client.time_series.return_value = mock_ts

    monkeypatch.setenv("B1E55ED_TWELVEDATA_KEY", "test_key_123")

    with patch("yfinance.Ticker", return_value=mock_ticker), patch("twelvedata.TDClient", return_value=mock_td_client):
        feed = TradFiFeed(twelvedata_key="test_key_123")
        result = feed.get_ohlcv("SPY", interval="1h", bars=60)

    assert isinstance(result, list)
    assert len(result) > 0
    assert "close" in result[0]


def test_fallback_to_twelvedata_on_yfinance_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """When yfinance returns empty DataFrame, falls back to Twelve Data."""
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame()  # empty

    mock_td_df = _make_td_df(60)
    mock_ts = MagicMock()
    mock_ts.as_pandas.return_value = mock_td_df
    mock_td_client = MagicMock()
    mock_td_client.time_series.return_value = mock_ts

    with patch("yfinance.Ticker", return_value=mock_ticker), patch("twelvedata.TDClient", return_value=mock_td_client):
        feed = TradFiFeed(twelvedata_key="test_key_123")
        result = feed.get_ohlcv("SPY", interval="1h", bars=60)

    assert isinstance(result, list)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# Test: both fail → RuntimeError
# ---------------------------------------------------------------------------


def test_both_fail_raises_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """When both yfinance and Twelve Data fail, RuntimeError is raised."""
    mock_ticker = MagicMock()
    mock_ticker.history.side_effect = RuntimeError("yf down")

    mock_ts = MagicMock()
    mock_ts.as_pandas.side_effect = RuntimeError("td down")
    mock_td_client = MagicMock()
    mock_td_client.time_series.return_value = mock_ts

    with patch("yfinance.Ticker", return_value=mock_ticker), patch("twelvedata.TDClient", return_value=mock_td_client):
        feed = TradFiFeed(twelvedata_key="test_key_123")
        with pytest.raises(RuntimeError):
            feed.get_ohlcv("SPY", interval="1h", bars=60)


def test_yfinance_empty_no_twelvedata_key_raises() -> None:
    """When yfinance returns empty and no Twelve Data key → RuntimeError (no crash loop)."""
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame()

    with patch("yfinance.Ticker", return_value=mock_ticker):
        feed = TradFiFeed(twelvedata_key=None)
        with pytest.raises(RuntimeError, match="B1E55ED_TWELVEDATA_KEY"):
            feed.get_ohlcv("SPY", interval="1h", bars=60)


# ---------------------------------------------------------------------------
# Test: missing Twelve Data key → graceful skip (no crash)
# ---------------------------------------------------------------------------


def test_missing_twelvedata_key_skips_gracefully(monkeypatch: pytest.MonkeyPatch) -> None:
    """If B1E55ED_TWELVEDATA_KEY is not set, Twelve Data is not attempted.
    yfinance succeeds → result returned normally."""
    monkeypatch.delenv("B1E55ED_TWELVEDATA_KEY", raising=False)

    mock_df = _make_ohlcv_df(60)
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = mock_df

    with patch("yfinance.Ticker", return_value=mock_ticker):
        feed = TradFiFeed()
        result = feed.get_ohlcv("SPY", interval="1h", bars=60)

    assert len(result) == 60  # yfinance worked fine, Twelve Data never called


def test_missing_twelvedata_key_skips_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """Twelve Data is never imported or called when the key is absent and yfinance fails."""
    monkeypatch.delenv("B1E55ED_TWELVEDATA_KEY", raising=False)

    mock_ticker = MagicMock()
    mock_ticker.history.side_effect = RuntimeError("yf down")

    with patch("yfinance.Ticker", return_value=mock_ticker):
        feed = TradFiFeed(twelvedata_key=None)  # explicitly no key
        with pytest.raises(RuntimeError):
            feed.get_ohlcv("SPY", interval="1h", bars=60)
        # Should NOT reach twelvedata at all; just raises with helpful message


# ---------------------------------------------------------------------------
# Test: is_available
# ---------------------------------------------------------------------------


def test_is_available_returns_true_when_yfinance_works() -> None:
    mock_df = _make_ohlcv_df(10)
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = mock_df

    with patch("yfinance.Ticker", return_value=mock_ticker):
        feed = TradFiFeed()
        assert feed.is_available() is True


def test_is_available_returns_false_when_both_fail() -> None:
    mock_ticker = MagicMock()
    mock_ticker.history.side_effect = RuntimeError("down")

    with patch("yfinance.Ticker", return_value=mock_ticker):
        feed = TradFiFeed(twelvedata_key=None)
        assert feed.is_available() is False
