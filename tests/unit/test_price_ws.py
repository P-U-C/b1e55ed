"""Tests for engine.producers.price_ws — symbol subscription coverage."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from engine.core.config import Config, UniverseBundle, UniverseConfig
from engine.producers.price_ws import PriceAlertsProducer


def _make_producer_with_config(config: Config) -> PriceAlertsProducer:
    """Create a PriceAlertsProducer with a mocked context carrying *config*."""
    ctx = MagicMock()
    ctx.config = config
    ctx.logger = MagicMock()
    producer = PriceAlertsProducer.__new__(PriceAlertsProducer)
    producer.ctx = ctx
    return producer


def test_all_subscribed_symbols_includes_bundle_symbols() -> None:
    """Bundle-only symbols (e.g. DOGE in crypto-core) must appear in the subscription list."""
    universe = UniverseConfig(
        symbols=["BTC", "ETH"],
        bundles=[
            UniverseBundle(
                id="crypto-core",
                name="Crypto Core",
                symbols=["BTC", "ETH", "SOL", "DOGE"],
                enabled=True,
            ),
        ],
    )
    cfg = Config(universe=universe)
    producer = _make_producer_with_config(cfg)

    syms = producer._all_subscribed_symbols()

    # DOGE is only in the bundle, not in universe.symbols — must still be included
    assert "DOGE" in syms
    assert "SOL" in syms
    # No duplicates
    assert len(syms) == len(set(syms))


def test_all_subscribed_symbols_empty_bundles_uses_explicit() -> None:
    """When no bundles are configured, explicit universe.symbols are used."""
    universe = UniverseConfig(symbols=["BTC", "ETH"])
    cfg = Config(universe=universe)
    producer = _make_producer_with_config(cfg)

    syms = producer._all_subscribed_symbols()
    assert syms == ["BTC", "ETH"]


def test_all_subscribed_symbols_disabled_bundle_excluded() -> None:
    """Disabled bundles must not contribute symbols."""
    universe = UniverseConfig(
        symbols=["BTC"],
        bundles=[
            UniverseBundle(
                id="disabled-bundle",
                name="Disabled",
                symbols=["XRP", "ADA"],
                enabled=False,
            ),
        ],
    )
    cfg = Config(universe=universe)
    producer = _make_producer_with_config(cfg)

    syms = producer._all_subscribed_symbols()
    assert "XRP" not in syms
    assert "ADA" not in syms
    assert "BTC" in syms
