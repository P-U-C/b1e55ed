"""Tests for independent p_true estimation methods in PolymarketProducer."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock

import httpx
import pytest

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from engine.core.client import DataClient
from engine.core.config import Config
from engine.core.database import Database
from engine.core.metrics import MetricsRegistry
from engine.producers.base import ProducerContext
from engine.producers.polymarket import PolymarketProducer, _norm_cdf

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_ctx() -> ProducerContext:
    config = Mock(spec=Config)
    config.universe = Mock()
    config.universe.symbols = []

    return ProducerContext(
        config=config,
        db=Mock(spec=Database),
        client=Mock(spec=DataClient),
        metrics=Mock(spec=MetricsRegistry),
        logger=Mock(spec=logging.Logger),
    )


@pytest.fixture()
def producer(mock_ctx: ProducerContext) -> PolymarketProducer:
    p = PolymarketProducer(mock_ctx)
    p._binance_price_cache = {}
    return p


def _make_market(
    *,
    slug: str = "test-market",
    question: str = "",
    best_bid: float = 0.45,
    best_ask: float = 0.55,
    delta_24h: float = 0.0,
    liquidity: float = 50_000.0,
    end_date: str | None = "2099-12-31T00:00:00Z",
) -> dict:
    """Create a minimal market dict for testing."""
    probability = (best_bid + best_ask) / 2.0
    return {
        "id": f"id-{slug}",
        "slug": slug,
        "question": question or f"Test market: {slug}",
        "bestBid": best_bid,
        "bestAsk": best_ask,
        "outcomePrices": json.dumps([str(probability), str(1.0 - probability)]),
        "oneDayPriceChange": delta_24h,
        "liquidity": liquidity,
        "volume24hr": 10_000.0,
        "endDate": end_date,
    }


def _mock_client_with_binance(price: float) -> MagicMock:
    """Return a mock httpx.Client that serves a Binance price response."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"price": str(price)}
    mock_resp.raise_for_status = MagicMock()

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.return_value = mock_resp
    return mock_client


# ── _norm_cdf ─────────────────────────────────────────────────────────────────


def test_gbm_norm_cdf_zero() -> None:
    """N(0) should be exactly 0.5."""
    assert _norm_cdf(0) == pytest.approx(0.5)


def test_gbm_norm_cdf_positive() -> None:
    """N(1.96) should be approximately 0.975."""
    assert _norm_cdf(1.96) == pytest.approx(0.975, abs=0.001)


def test_gbm_norm_cdf_negative() -> None:
    """N(-1.96) ≈ 0.025 (symmetric)."""
    assert _norm_cdf(-1.96) == pytest.approx(0.025, abs=0.001)


# ── Method 1: GBM ────────────────────────────────────────────────────────────


def test_gbm_p_true_btc_above_target(producer: PolymarketProducer) -> None:
    """BTC spot 74k vs $90k target → OTM → p_true in reasonable range (0.1–0.5)."""
    # April 15 is ~28 days away from mid-March; use a relative date
    expiry = (datetime.now(tz=UTC) + timedelta(days=28)).strftime("%Y-%m-%dT00:00:00Z")
    market = _make_market(
        slug="will-bitcoin-hit-90k-by-april-15",
        question="Will bitcoin hit $90k by April 15?",
        best_bid=0.30,
        best_ask=0.40,
        end_date=expiry,
    )

    mock_client = _mock_client_with_binance(74_000.0)

    p_true, method = producer._estimate_p_true(
        market=market,
        mid_price=0.35,
        best_bid=0.30,
        best_ask=0.40,
        probability_delta_24h=0.02,
        liquidity_usd=200_000.0,
        resolves_at_str=expiry,
        client=mock_client,
    )

    assert method == "gbm"
    assert 0.05 <= p_true <= 0.55, f"Expected OTM probability, got {p_true:.4f}"


def test_gbm_p_true_below_current(producer: PolymarketProducer) -> None:
    """BTC spot 74k vs $50k target — target already exceeded → high probability."""
    expiry = (datetime.now(tz=UTC) + timedelta(days=13)).strftime("%Y-%m-%dT00:00:00Z")
    market = _make_market(
        slug="will-bitcoin-reach-50k-by-march-31",
        question="Will bitcoin reach $50k by March 31?",
        best_bid=0.90,
        best_ask=0.95,
        end_date=expiry,
    )

    mock_client = _mock_client_with_binance(74_000.0)

    p_true, method = producer._estimate_p_true(
        market=market,
        mid_price=0.925,
        best_bid=0.90,
        best_ask=0.95,
        probability_delta_24h=0.01,
        liquidity_usd=200_000.0,
        resolves_at_str=expiry,
        client=mock_client,
    )

    assert method == "gbm"
    assert p_true >= 0.90, f"Expected high probability for in-the-money target, got {p_true:.4f}"


def test_gbm_uses_k_suffix_slug(producer: PolymarketProducer) -> None:
    """Slugs like 'will-bitcoin-hit-150k-by-dec-31' should trigger GBM via k suffix."""
    expiry = (datetime.now(tz=UTC) + timedelta(days=90)).strftime("%Y-%m-%dT00:00:00Z")
    market = _make_market(
        slug="will-bitcoin-hit-150k-by-dec-31",
        question="Will bitcoin hit 150k by December 31?",
        best_bid=0.10,
        best_ask=0.20,
        end_date=expiry,
    )

    mock_client = _mock_client_with_binance(84_000.0)

    p_true, method = producer._estimate_p_true(
        market=market,
        mid_price=0.15,
        best_bid=0.10,
        best_ask=0.20,
        probability_delta_24h=0.02,
        liquidity_usd=300_000.0,
        resolves_at_str=expiry,
        client=mock_client,
    )

    assert method == "gbm"
    # BTC at 84k vs 150k target, 90 days: should be low probability
    assert 0.0 <= p_true <= 0.40


def test_gbm_falls_through_on_binance_failure(producer: PolymarketProducer) -> None:
    """If Binance fetch fails, GBM falls through to next method."""
    expiry = (datetime.now(tz=UTC) + timedelta(days=28)).strftime("%Y-%m-%dT00:00:00Z")
    market = _make_market(
        slug="will-bitcoin-hit-90k-by-april-15",
        question="Will bitcoin hit $90k by April 15?",
        best_bid=0.33,  # spread = 0.37 - 0.33 = 0.04 < 0.05 → no spread_anomaly
        best_ask=0.37,
        delta_24h=0.10,  # enough for momentum
        end_date=expiry,
    )

    # Simulate Binance returning an error
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.side_effect = httpx.ConnectError("network down")

    p_true, method = producer._estimate_p_true(
        market=market,
        mid_price=0.35,
        best_bid=0.33,
        best_ask=0.37,
        probability_delta_24h=0.10,
        liquidity_usd=200_000.0,
        resolves_at_str=expiry,
        client=mock_client,
    )

    # Should fall to momentum (delta >= 0.08)
    assert method == "momentum"
    assert p_true == pytest.approx(0.35 + 0.5 * 0.10)


# ── Method 2: Near-resolution ─────────────────────────────────────────────────


def test_near_resolution_boost(producer: PolymarketProducer) -> None:
    """Market resolves in 24h with negative delta → p_true < mid_price."""
    resolves_at = (datetime.now(tz=UTC) + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    market = _make_market(
        slug="will-something-happen-today",
        question="Will something happen today?",
        best_bid=0.30,
        best_ask=0.40,
        delta_24h=-0.15,
        end_date=resolves_at,
    )

    mock_client = MagicMock(spec=httpx.Client)

    p_true, method = producer._estimate_p_true(
        market=market,
        mid_price=0.35,
        best_bid=0.30,
        best_ask=0.40,
        probability_delta_24h=-0.15,
        liquidity_usd=50_000.0,
        resolves_at_str=resolves_at,
        client=mock_client,
    )

    assert method == "near_resolution"
    assert p_true < 0.35, f"Expected p_true below mid_price=0.35, got {p_true:.4f}"


def test_near_resolution_not_triggered_far_expiry(producer: PolymarketProducer) -> None:
    """Market expiring in 10 days should NOT use near_resolution method."""
    resolves_at = (datetime.now(tz=UTC) + timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    market = _make_market(
        slug="will-something-happen-in-ten-days",
        question="Will something happen in ten days?",
        best_bid=0.30,
        best_ask=0.40,
        delta_24h=-0.15,
        end_date=resolves_at,
    )

    mock_client = MagicMock(spec=httpx.Client)

    _p_true, method = producer._estimate_p_true(
        market=market,
        mid_price=0.35,
        best_bid=0.30,
        best_ask=0.40,
        probability_delta_24h=-0.15,
        liquidity_usd=50_000.0,
        resolves_at_str=resolves_at,
        client=mock_client,
    )

    assert method != "near_resolution"


# ── Method 3: Spread anomaly ──────────────────────────────────────────────────


def test_spread_anomaly_detected(producer: PolymarketProducer) -> None:
    """Bid=0.40, ask=0.50 (10% spread), liquidity=200k, delta=0.10 → spread_anomaly."""
    market = _make_market(
        slug="will-the-fed-pause-in-july",
        question="Will the Fed pause in July?",
        best_bid=0.40,
        best_ask=0.50,
        delta_24h=0.10,
        liquidity=200_000.0,
        end_date="2026-07-31T00:00:00Z",
    )

    mock_client = MagicMock(spec=httpx.Client)

    p_true, method = producer._estimate_p_true(
        market=market,
        mid_price=0.45,
        best_bid=0.40,
        best_ask=0.50,
        probability_delta_24h=0.10,
        liquidity_usd=200_000.0,
        resolves_at_str="2026-07-31T00:00:00Z",
        client=mock_client,
    )

    assert method == "spread_anomaly"
    # boost = 0.10 * 0.4 = 0.04; p_true = 0.45 + 0.04 = 0.49
    assert p_true == pytest.approx(0.49, abs=0.01)


def test_spread_anomaly_not_triggered_thin_market(producer: PolymarketProducer) -> None:
    """Thin market (< 100k liquidity) should NOT trigger spread_anomaly."""
    market = _make_market(
        slug="thin-market",
        question="Thin market question?",
        best_bid=0.40,
        best_ask=0.50,
        delta_24h=0.10,
        liquidity=50_000.0,
    )

    mock_client = MagicMock(spec=httpx.Client)

    _p_true, method = producer._estimate_p_true(
        market=market,
        mid_price=0.45,
        best_bid=0.40,
        best_ask=0.50,
        probability_delta_24h=0.10,
        liquidity_usd=50_000.0,
        resolves_at_str="2026-12-31T00:00:00Z",
        client=mock_client,
    )

    # Falls through spread_anomaly (thin) → momentum (delta=0.10 >= 0.08)
    assert method == "momentum"


def test_spread_anomaly_not_triggered_negative_boost(producer: PolymarketProducer) -> None:
    """Spread anomaly only fires when boost > 0 (positive delta)."""
    market = _make_market(
        slug="liquid-falling-market",
        question="Liquid falling market?",
        best_bid=0.40,
        best_ask=0.50,
        delta_24h=-0.10,
        liquidity=200_000.0,
    )

    mock_client = MagicMock(spec=httpx.Client)

    _p_true, method = producer._estimate_p_true(
        market=market,
        mid_price=0.45,
        best_bid=0.40,
        best_ask=0.50,
        probability_delta_24h=-0.10,
        liquidity_usd=200_000.0,
        resolves_at_str="2026-12-31T00:00:00Z",
        client=mock_client,
    )

    # Negative boost → skip spread_anomaly → falls to momentum
    assert method == "momentum"


# ── Method 5: market_price fallback ──────────────────────────────────────────


def test_market_price_fallback(producer: PolymarketProducer) -> None:
    """No special conditions → falls through to market_price."""
    market = _make_market(
        slug="boring-market",
        question="Will nothing interesting happen?",
        best_bid=0.45,
        best_ask=0.55,
        delta_24h=0.01,
        liquidity=30_000.0,
        end_date="2026-12-31T00:00:00Z",
    )

    mock_client = MagicMock(spec=httpx.Client)

    p_true, method = producer._estimate_p_true(
        market=market,
        mid_price=0.50,
        best_bid=0.45,
        best_ask=0.55,
        probability_delta_24h=0.01,
        liquidity_usd=30_000.0,
        resolves_at_str="2026-12-31T00:00:00Z",
        client=mock_client,
    )

    assert method == "market_price"
    assert p_true == pytest.approx(0.50)


# ── _parse_crypto_target ──────────────────────────────────────────────────────


def test_parse_crypto_target_dollar_k(producer: PolymarketProducer) -> None:
    assert producer._parse_crypto_target("will bitcoin hit $90k by april 15") == ("BTC", 90_000.0)


def test_parse_crypto_target_dollar_comma(producer: PolymarketProducer) -> None:
    assert producer._parse_crypto_target("Will Bitcoin exceed $100,000 in 2026?") == ("BTC", 100_000.0)


def test_parse_crypto_target_k_suffix_no_dollar(producer: PolymarketProducer) -> None:
    assert producer._parse_crypto_target("will-bitcoin-hit-150k-by-september-30") == ("BTC", 150_000.0)


def test_parse_crypto_target_no_match_bare_number(producer: PolymarketProducer) -> None:
    """Bare numbers without $ or k (like years) should NOT match."""
    result = producer._parse_crypto_target("will ethereum reach 5000 in 2026")
    assert result is None


def test_parse_crypto_target_eth(producer: PolymarketProducer) -> None:
    assert producer._parse_crypto_target("Will ETH hit $5k by June?") == ("ETH", 5_000.0)


def test_parse_crypto_target_sol(producer: PolymarketProducer) -> None:
    assert producer._parse_crypto_target("Will Solana reach $500 by end of year?") == ("SOL", 500.0)


def test_parse_crypto_target_no_crypto_symbol(producer: PolymarketProducer) -> None:
    assert producer._parse_crypto_target("Will the market hit $50k?") is None


# ── Binance cache ─────────────────────────────────────────────────────────────


def test_binance_cache_reuses_price(producer: PolymarketProducer) -> None:
    """_fetch_spot_price should only call Binance once per symbol per run."""
    mock_client = _mock_client_with_binance(80_000.0)

    price1 = producer._fetch_spot_price("BTC", client=mock_client)
    price2 = producer._fetch_spot_price("BTC", client=mock_client)

    assert price1 == 80_000.0
    assert price2 == 80_000.0
    # Only one actual HTTP call
    assert mock_client.get.call_count == 1


def test_binance_cache_reset_on_normalize(mock_ctx: ProducerContext) -> None:
    """Cache should be reset at the start of each normalize() call."""
    producer = PolymarketProducer(mock_ctx)
    producer._binance_price_cache = {"BTC": 99_999.0}

    # normalize() with empty list still resets cache
    producer.normalize([])

    # Cache is reset — stale value is gone
    assert producer._binance_price_cache == {}


# ── Existing behavior preservation ───────────────────────────────────────────


def test_existing_momentum_still_works(mock_ctx: ProducerContext) -> None:
    """Fed-cut market with strong delta still uses momentum method."""
    producer = PolymarketProducer(mock_ctx)
    market = {
        "id": "m-momentum",
        "slug": "will-the-fed-cut-rates-in-march-2026",
        "question": "Question for will-the-fed-cut-rates-in-march-2026",
        "bestBid": 0.50,
        "bestAsk": 0.50,
        "outcomePrices": json.dumps(["0.50", "0.50"]),
        "oneDayPriceChange": 0.10,
        "liquidity": 700_000.0,
        "volume24hr": 50_000.0,
        "endDate": "2026-12-31T00:00:00Z",
    }

    events = producer.normalize([market])

    assert len(events) == 1
    payload = events[0].payload
    assert payload["p_true_method"] == "momentum"
    assert payload["p_true_estimate"] == pytest.approx(0.55)
