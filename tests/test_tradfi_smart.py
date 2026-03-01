"""Tests for S3 Smart TradFi Producer — self-contained Binance + rule-based signals."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from engine.core.events import TradFiSignalPayload
from engine.producers.tradfi import (
    TradFiBasisProducer,
    _compute_signal,
    _fetch_binance,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(symbols=None):
    ctx = MagicMock()
    ctx.config.universe.symbols = symbols or ["BTC", "ETH", "SOL"]
    ctx.logger = MagicMock()
    ctx.db = MagicMock()
    ctx.metrics = MagicMock()
    ctx.client = MagicMock()
    return ctx


def _make_producer(symbols=None) -> TradFiBasisProducer:
    ctx = _make_ctx(symbols)
    p = TradFiBasisProducer.__new__(TradFiBasisProducer)
    p.ctx = ctx
    p.name = "tradfi-basis"
    p._bus = None
    return p


def _binance_response(url, **kwargs):
    """Route mock responses based on URL."""
    url_str = str(url)

    if "dapi.binance.com" in url_str and "ticker/price" in url_str:
        return httpx.Response(
            200,
            json=[
                {"symbol": "BTCUSD_250328", "price": "105000.0", "ps": "BTCUSD"},
                {"symbol": "ETHUSD_250328", "price": "4200.0", "ps": "ETHUSD"},
                {"symbol": "BTCUSD_250627", "price": "108000.0", "ps": "BTCUSD"},
            ],
            request=httpx.Request("GET", url_str),
        )
    if "api.binance.com" in url_str and "ticker/price" in url_str:
        params = kwargs.get("params", {})
        sym = params.get("symbol", "")
        prices = {"BTCUSDT": "100000.0", "ETHUSDT": "4000.0", "SOLUSDT": "200.0"}
        return httpx.Response(
            200,
            json={"symbol": sym, "price": prices.get(sym, "0")},
            request=httpx.Request("GET", url_str),
        )
    if "fapi.binance.com" in url_str and "fundingRate" in url_str:
        return httpx.Response(
            200,
            json=[{"fundingRate": "0.0001", "fundingTime": 1700000000000}],
            request=httpx.Request("GET", url_str),
        )
    if "fapi.binance.com" in url_str and "openInterest" in url_str:
        return httpx.Response(
            200,
            json={"symbol": "BTCUSDT", "openInterest": "50000.0"},
            request=httpx.Request("GET", url_str),
        )
    return httpx.Response(200, json={}, request=httpx.Request("GET", url_str))


class MockAsyncClient:
    """Mock httpx.AsyncClient that routes by URL."""

    async def get(self, url, **kwargs):
        return _binance_response(url, **kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass


# ---------------------------------------------------------------------------
# Signal logic tests
# ---------------------------------------------------------------------------


class TestComputeSignal:
    def test_tradfi_meltup_score_4_is_long_0_75(self):
        d, c, r = _compute_signal(5.0, 10.0, 4)
        assert d == "long"
        assert c == 0.75
        assert "meltup_score=4" in r

    def test_tradfi_basis_crowded_is_short(self):
        d, c, r = _compute_signal(9.5, 10.0, None)
        assert d == "short"
        assert c == 0.60
        assert "crowded" in r

    def test_tradfi_basis_unwound_negative_funding(self):
        d, c, r = _compute_signal(1.5, -5.0, None)
        assert d == "short"
        assert c == 0.65
        assert "unwound" in r

    def test_tradfi_basis_healthy_with_funding(self):
        d, c, r = _compute_signal(4.5, 10.0, None)
        assert d == "long"
        assert c == 0.55
        assert "healthy" in r and "funding normal" in r

    def test_tradfi_basis_healthy_early_setup(self):
        d, c, r = _compute_signal(4.5, None, None)
        assert d == "long"
        assert c == 0.45
        assert "early setup" in r

    def test_tradfi_no_signal_is_flat(self):
        d, c, r = _compute_signal(None, None, None)
        assert d == "flat"
        assert c == 0.0
        assert "no clear" in r


# ---------------------------------------------------------------------------
# Producer integration tests
# ---------------------------------------------------------------------------


class TestTradFiProducer:
    @patch.dict("os.environ", {}, clear=True)
    def test_tradfi_self_contained_no_env_var(self):
        """Producer runs without B1E55ED_TRADFI_BASIS_URL using Binance."""
        p = _make_producer()
        with patch(
            "engine.producers.tradfi.httpx.AsyncClient",
            return_value=MockAsyncClient(),
        ):
            raw = p.collect()
        assert len(raw) >= 1
        assert all("symbol" in r for r in raw)

    @patch.dict(
        "os.environ",
        {"B1E55ED_TRADFI_BASIS_URL": "http://legacy.test/basis"},
        clear=False,
    )
    def test_tradfi_fallback_to_env_url_if_set(self):
        """If env var set, uses old HTTP path."""
        p = _make_producer()
        p.ctx.client.request_json = AsyncMock(
            return_value=[
                {
                    "symbol": "BTC",
                    "basis_annualized": 5.0,
                    "funding_annualized": 10.0,
                }
            ]
        )
        raw = p.collect()
        assert len(raw) == 1
        assert raw[0]["symbol"] == "BTC"

    @patch.dict("os.environ", {}, clear=True)
    def test_tradfi_binance_calls_mocked(self):
        """Verify correct Binance endpoints are called."""
        calls: list[str] = []

        class TrackingClient:
            async def get(self, url, **kwargs):
                calls.append(str(url))
                return _binance_response(url, **kwargs)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

        result = asyncio.run(_fetch_binance(TrackingClient(), ["BTC", "ETH", "SOL"]))
        assert len(result) == 3

        urls_joined = " ".join(calls)
        assert "dapi.binance.com" in urls_joined
        assert "api.binance.com" in urls_joined
        assert "fapi.binance.com" in urls_joined

    @patch.dict("os.environ", {}, clear=True)
    def test_tradfi_normalize_wires_signal(self):
        """normalize() sets direction/confidence/signal_reason on payload."""
        p = _make_producer()
        raw = [
            {
                "symbol": "BTC",
                "basis_annualized": 9.0,
                "funding_annualized": 5.0,
                "meltup_score": None,
            }
        ]
        events = p.normalize(raw)
        assert len(events) == 1
        payload = events[0].payload
        assert payload["direction"] == "short"
        assert payload["confidence"] == 0.60
        assert payload["signal_reason"] is not None


# ---------------------------------------------------------------------------
# Payload model tests
# ---------------------------------------------------------------------------


class TestTradFiSignalPayload:
    def test_new_fields_defaults(self):
        p = TradFiSignalPayload(symbol="BTC")
        assert p.direction is None
        assert p.confidence is None
        assert p.horizon == "swing"
        assert p.invalidation is None
        assert p.signal_reason is None

    def test_new_fields_set(self):
        p = TradFiSignalPayload(
            symbol="ETH",
            direction="long",
            confidence=0.55,
            horizon="intraday",
            invalidation=3800.0,
            signal_reason="test",
        )
        assert p.direction == "long"
        assert p.confidence == 0.55
