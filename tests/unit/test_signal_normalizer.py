"""Tests for SQ1: Signal normalization relative to asset scale."""

from __future__ import annotations

import pytest

from engine.brain.signal_normalizer import (
    AssetMetrics,
    NormalizedSignals,
    SignalNormalizer,
    normalize_onchain_signal,
)


class TestSignalNormalizer:
    def test_basic_normalization(self) -> None:
        normalizer = SignalNormalizer()
        result = normalizer.normalize(
            "BTC",
            whale_netflow=1_000_000_000,  # $1B
            exchange_flow=500_000_000,  # $500M
            active_addresses_change=2.5,  # 2.5%
            price_momentum_24h=5.0,  # 5%
        )
        assert isinstance(result, NormalizedSignals)
        # All values should be in 0-1 range
        for field in ["whale_netflow", "exchange_flow", "active_addresses_change", "price_momentum_24h"]:
            val = getattr(result, field)
            assert val is not None
            assert 0.0 <= val <= 1.0

    def test_neutral_values(self) -> None:
        """Zero flow should produce ~0.5 (neutral) scores."""
        normalizer = SignalNormalizer()
        result = normalizer.normalize(
            "BTC",
            whale_netflow=0.0,
            exchange_flow=0.0,
            active_addresses_change=0.0,
            price_momentum_24h=0.0,
        )
        assert result.whale_netflow == pytest.approx(0.5, abs=0.01)
        assert result.exchange_flow == pytest.approx(0.5, abs=0.01)
        assert result.active_addresses_change == pytest.approx(0.5, abs=0.01)
        assert result.price_momentum_24h == pytest.approx(0.5, abs=0.01)

    def test_positive_whale_flow_bullish(self) -> None:
        """Positive whale netflow (buying) should produce > 0.5 score."""
        normalizer = SignalNormalizer()
        # BTC default market cap ~$1T, 0.1% = $1B
        result = normalizer.normalize("BTC", whale_netflow=1_000_000_000)
        assert result.whale_netflow is not None
        assert result.whale_netflow > 0.5

    def test_negative_whale_flow_bearish(self) -> None:
        """Negative whale netflow (selling) should produce < 0.5 score."""
        normalizer = SignalNormalizer()
        result = normalizer.normalize("BTC", whale_netflow=-1_000_000_000)
        assert result.whale_netflow is not None
        assert result.whale_netflow < 0.5

    def test_exchange_inflow_bearish(self) -> None:
        """Positive exchange flow (depositing to sell) should produce < 0.5 score."""
        normalizer = SignalNormalizer()
        result = normalizer.normalize("BTC", exchange_flow=500_000_000)
        assert result.exchange_flow is not None
        assert result.exchange_flow < 0.5

    def test_exchange_outflow_bullish(self) -> None:
        """Negative exchange flow (withdrawing to hold) should produce > 0.5 score."""
        normalizer = SignalNormalizer()
        result = normalizer.normalize("BTC", exchange_flow=-500_000_000)
        assert result.exchange_flow is not None
        assert result.exchange_flow > 0.5

    def test_same_dollar_different_asset_different_score(self) -> None:
        """Same dollar flow should produce different scores for different cap assets."""
        normalizer = SignalNormalizer()
        normalizer.set_metrics("BIGCAP", AssetMetrics("BIGCAP", market_cap_usd=100_000_000_000))
        normalizer.set_metrics("SMALLCAP", AssetMetrics("SMALLCAP", market_cap_usd=100_000_000))

        flow = 10_000_000  # $10M

        big_result = normalizer.normalize("BIGCAP", whale_netflow=flow)
        small_result = normalizer.normalize("SMALLCAP", whale_netflow=flow)

        # Same dollar flow should be more significant for smaller cap
        assert big_result.whale_netflow is not None
        assert small_result.whale_netflow is not None
        assert small_result.whale_netflow > big_result.whale_netflow

    def test_clamping(self) -> None:
        """Extreme values should be clamped to 0-1."""
        normalizer = SignalNormalizer()
        # Huge inflow
        result = normalizer.normalize("BTC", whale_netflow=100_000_000_000_000)  # $100T
        assert result.whale_netflow == 1.0

        # Huge outflow
        result = normalizer.normalize("BTC", whale_netflow=-100_000_000_000_000)
        assert result.whale_netflow == 0.0

    def test_missing_values(self) -> None:
        """Missing inputs should produce None outputs."""
        normalizer = SignalNormalizer()
        result = normalizer.normalize("BTC")
        assert result.whale_netflow is None
        assert result.exchange_flow is None
        assert result.active_addresses_change is None
        assert result.price_momentum_24h is None

    def test_custom_metrics(self) -> None:
        """Custom metrics should override defaults."""
        normalizer = SignalNormalizer()
        custom = AssetMetrics("CUSTOM", market_cap_usd=50_000_000, volume_24h_usd=5_000_000)

        # $500K flow = 1% of market cap = significant
        result = normalizer.normalize("CUSTOM", whale_netflow=500_000, metrics=custom)
        assert result.whale_netflow is not None
        assert result.whale_netflow > 0.9  # Very bullish

    def test_default_fallback(self) -> None:
        """Unknown symbols should use DEFAULT metrics."""
        normalizer = SignalNormalizer()
        result = normalizer.normalize("UNKNOWNTOKEN", whale_netflow=1_000_000)
        assert result.whale_netflow is not None
        # Should produce some score using default metrics

    def test_normalize_raw_dict(self) -> None:
        """normalize_raw should handle dict input."""
        normalizer = SignalNormalizer()
        features = {
            "whale_netflow": 1_000_000_000,
            "exchange_flow": None,
            "active_addresses_change": 3.0,
            "other_field": "ignored",
        }
        result = normalizer.normalize_raw("BTC", features)
        assert result.whale_netflow is not None
        assert result.exchange_flow is None
        assert result.active_addresses_change is not None


class TestConvenienceFunction:
    def test_normalize_onchain_signal(self) -> None:
        """Test the convenience function."""
        features = {
            "whale_netflow": 500_000_000,
            "price_momentum_24h": 2.0,
        }
        result = normalize_onchain_signal("ETH", features)
        assert isinstance(result, NormalizedSignals)
        assert result.whale_netflow is not None
        assert result.price_momentum_24h is not None


class TestIntegrationWithSynthesis:
    def test_synthesis_uses_normalizer(self) -> None:
        """Verify synthesis domain_score uses the normalizer for onchain."""
        from engine.brain.synthesis import VectorSynthesis

        synth = VectorSynthesis.__new__(VectorSynthesis)
        synth.config = type("Config", (), {"weights": type("W", (), {"model_dump": lambda: {}})()})()

        # Test with on-chain features
        features = {
            "whale_netflow": 1_000_000_000.0,
            "exchange_flow": 500_000_000.0,
        }
        score = synth.domain_score("onchain", features, symbol="BTC")

        assert score is not None
        assert 0.0 <= score <= 1.0
