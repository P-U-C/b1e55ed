"""engine.brain.signal_normalizer

Signal normalization relative to asset scale (SQ1).

Problem: A $200M whale flow means different things for BTC ($1T+ market cap)
vs a small cap ($100M market cap). Without normalization, the same raw number
produces very different signal strengths inappropriately.

Solution: Normalize flows relative to:
- Market cap (primary)
- Daily volume (fallback)
- Circulating supply considerations

Reference scales (calibrated to produce 0-1 signals):
- Whale flow: 0.1% of market cap = meaningful signal
- Exchange flow: 0.5% of daily volume = meaningful signal
- Active address change: 5% change = meaningful signal

Easter egg: The map is not the territory, but a good map helps.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class AssetMetrics:
    """Reference metrics for signal normalization."""

    symbol: str
    market_cap_usd: float | None = None
    volume_24h_usd: float | None = None
    circulating_supply: float | None = None


# Fallback reference values when market cap unavailable
# Based on typical ranges for liquid crypto assets
DEFAULT_REFERENCE_SCALES = {
    "BTC": AssetMetrics("BTC", market_cap_usd=1_000_000_000_000, volume_24h_usd=30_000_000_000),
    "ETH": AssetMetrics("ETH", market_cap_usd=400_000_000_000, volume_24h_usd=15_000_000_000),
    "SOL": AssetMetrics("SOL", market_cap_usd=80_000_000_000, volume_24h_usd=3_000_000_000),
    "DEFAULT": AssetMetrics("DEFAULT", market_cap_usd=1_000_000_000, volume_24h_usd=100_000_000),
}


@dataclass(frozen=True, slots=True)
class NormalizedSignals:
    """Normalized on-chain signals (0-1 scale, 0.5 = neutral)."""

    whale_netflow: float | None = None  # 0 = outflow, 0.5 = neutral, 1 = inflow
    exchange_flow: float | None = None  # 0 = inflow (bearish), 0.5 = neutral, 1 = outflow (bullish)
    active_addresses_change: float | None = None  # 0 = declining, 0.5 = neutral, 1 = growing
    price_momentum_24h: float | None = None  # 0 = down, 0.5 = flat, 1 = up


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class SignalNormalizer:
    """Normalize raw on-chain signals relative to asset scale.

    The key insight: signal strength should be proportional to what's
    *meaningful for that asset*, not absolute dollar values.

    A 0.1% market cap whale flow is meaningful for any asset.
    A $100M flow is noise for BTC but massive for a small cap.
    """

    def __init__(
        self,
        *,
        whale_flow_scale: float = 0.001,  # 0.1% of market cap = full signal
        exchange_flow_scale: float = 0.005,  # 0.5% of daily volume = full signal
        address_change_scale: float = 0.05,  # 5% change = full signal
        momentum_scale: float = 0.10,  # 10% price change = full signal
    ) -> None:
        self.whale_flow_scale = whale_flow_scale
        self.exchange_flow_scale = exchange_flow_scale
        self.address_change_scale = address_change_scale
        self.momentum_scale = momentum_scale
        self._metrics_cache: dict[str, AssetMetrics] = {}

    def set_metrics(self, symbol: str, metrics: AssetMetrics) -> None:
        """Cache asset metrics for normalization."""
        self._metrics_cache[symbol.upper()] = metrics

    def get_metrics(self, symbol: str) -> AssetMetrics:
        """Get metrics for symbol, falling back to defaults."""
        sym = symbol.upper()
        if sym in self._metrics_cache:
            return self._metrics_cache[sym]
        if sym in DEFAULT_REFERENCE_SCALES:
            return DEFAULT_REFERENCE_SCALES[sym]
        return DEFAULT_REFERENCE_SCALES["DEFAULT"]

    def normalize(
        self,
        symbol: str,
        *,
        whale_netflow: float | None = None,
        exchange_flow: float | None = None,
        active_addresses_change: float | None = None,
        price_momentum_24h: float | None = None,
        metrics: AssetMetrics | None = None,
    ) -> NormalizedSignals:
        """Normalize raw signals relative to asset scale.

        Parameters
        ----------
        symbol:
            Asset symbol (e.g., "BTC").
        whale_netflow:
            Raw whale netflow in USD (positive = inflow).
        exchange_flow:
            Raw exchange flow in USD (positive = inflow to exchanges, bearish).
        active_addresses_change:
            Percentage change in active addresses.
        price_momentum_24h:
            24h price change percentage.
        metrics:
            Override asset metrics (optional).

        Returns
        -------
        NormalizedSignals
            All values on 0-1 scale, 0.5 = neutral.
        """
        m = metrics or self.get_metrics(symbol)

        norm_whale: float | None = None
        norm_exchange: float | None = None
        norm_addresses: float | None = None
        norm_momentum: float | None = None

        # Whale netflow: normalize to market cap
        if whale_netflow is not None and m.market_cap_usd and m.market_cap_usd > 0:
            # Scale: 0.1% of market cap = move from 0.5 to 0 or 1
            relative_flow = whale_netflow / m.market_cap_usd
            norm_whale = _clamp01(0.5 + relative_flow / self.whale_flow_scale)

        # Exchange flow: normalize to daily volume (inflow = bearish)
        if exchange_flow is not None:
            reference = m.volume_24h_usd or m.market_cap_usd
            if reference and reference > 0:
                relative_flow = exchange_flow / reference
                # Negative because inflow to exchanges is bearish
                norm_exchange = _clamp01(0.5 - relative_flow / self.exchange_flow_scale)

        # Active addresses: already a percentage
        if active_addresses_change is not None:
            norm_addresses = _clamp01(0.5 + active_addresses_change / (self.address_change_scale * 100))

        # Price momentum: already a percentage
        if price_momentum_24h is not None:
            norm_momentum = _clamp01(0.5 + price_momentum_24h / (self.momentum_scale * 100))

        return NormalizedSignals(
            whale_netflow=norm_whale,
            exchange_flow=norm_exchange,
            active_addresses_change=norm_addresses,
            price_momentum_24h=norm_momentum,
        )

    def normalize_raw(self, symbol: str, features: dict[str, Any]) -> NormalizedSignals:
        """Normalize a raw feature dict."""
        return self.normalize(
            symbol,
            whale_netflow=_safe_float(features.get("whale_netflow")),
            exchange_flow=_safe_float(features.get("exchange_flow")),
            active_addresses_change=_safe_float(features.get("active_addresses_change")),
            price_momentum_24h=_safe_float(features.get("price_momentum_24h")),
        )


# Default singleton for common use
_default_normalizer: SignalNormalizer | None = None


def get_normalizer() -> SignalNormalizer:
    """Get the default signal normalizer instance."""
    global _default_normalizer
    if _default_normalizer is None:
        _default_normalizer = SignalNormalizer()
    return _default_normalizer


def normalize_onchain_signal(symbol: str, features: dict[str, Any]) -> NormalizedSignals:
    """Convenience function for normalizing on-chain signals."""
    return get_normalizer().normalize_raw(symbol, features)
