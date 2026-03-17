"""Tests for universe.symbols / universe.bundles auto-derivation.

Verifies that:
1. Empty universe.symbols + enabled bundle → brain uses bundle symbols
2. Explicit universe.symbols + enabled bundle → brain uses union of both (deduped)
3. Disabled bundle symbols are NOT included
4. get_scoring_symbols mirrors active_symbols behaviour (without max_size cap)
"""

from __future__ import annotations

from engine.core.config import UniverseBundle, UniverseConfig, get_scoring_symbols

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bundle(
    bundle_id: str,
    symbols: list[str],
    *,
    enabled: bool = True,
) -> UniverseBundle:
    return UniverseBundle(
        id=bundle_id,
        name=bundle_id,
        symbols=symbols,
        enabled=enabled,
    )


def _universe(
    symbols: list[str] | None = None,
    bundles: list[UniverseBundle] | None = None,
) -> UniverseConfig:
    kwargs: dict = {}
    if symbols is not None:
        kwargs["symbols"] = symbols
    if bundles is not None:
        kwargs["bundles"] = bundles
    return UniverseConfig(**kwargs)


# ---------------------------------------------------------------------------
# get_scoring_symbols
# ---------------------------------------------------------------------------


class TestGetScoringSymbols:
    """Unit tests for the standalone get_scoring_symbols helper."""

    def test_empty_symbols_enabled_bundle_returns_bundle_symbols(self) -> None:
        """Scenario 1: no explicit symbols, one enabled bundle → bundle drives."""
        cfg = _universe(
            symbols=[],
            bundles=[_bundle("core", ["BTC", "ETH", "SOL"])],
        )
        assert get_scoring_symbols(cfg) == ["BTC", "ETH", "SOL"]

    def test_explicit_symbols_plus_enabled_bundle_returns_union(self) -> None:
        """Scenario 2: explicit symbols supplement bundle symbols (deduped union)."""
        cfg = _universe(
            symbols=["HYPE", "ETH"],  # ETH overlaps with bundle
            bundles=[_bundle("core", ["BTC", "ETH", "SOL"])],
        )
        result = get_scoring_symbols(cfg)
        # Bundle symbols come first, then non-overlapping explicit symbols appended
        assert result == ["BTC", "ETH", "SOL", "HYPE"]
        assert len(result) == len(set(result)), "Result must be deduplicated"

    def test_disabled_bundle_symbols_not_included(self) -> None:
        """Scenario 3: disabled bundles are excluded from the scoring universe."""
        cfg = _universe(
            symbols=[],
            bundles=[
                _bundle("active", ["BTC", "ETH"], enabled=True),
                _bundle("inactive", ["XRP", "DOGE"], enabled=False),
            ],
        )
        result = get_scoring_symbols(cfg)
        assert "XRP" not in result
        assert "DOGE" not in result
        assert result == ["BTC", "ETH"]

    def test_no_bundles_explicit_symbols_returned_as_is(self) -> None:
        """Backward-compat: no bundles configured → explicit symbols used directly."""
        cfg = _universe(symbols=["BTC", "SOL"])
        assert get_scoring_symbols(cfg) == ["BTC", "SOL"]

    def test_both_empty_returns_empty(self) -> None:
        """Edge case: no bundles, no symbols → empty list."""
        cfg = _universe(symbols=[], bundles=[])
        assert get_scoring_symbols(cfg) == []

    def test_bundle_symbols_come_before_explicit(self) -> None:
        """Bundle symbols maintain priority ordering over explicit supplements."""
        cfg = _universe(
            symbols=["AAPL"],
            bundles=[_bundle("crypto", ["BTC", "ETH"])],
        )
        result = get_scoring_symbols(cfg)
        assert result.index("BTC") < result.index("AAPL")
        assert result.index("ETH") < result.index("AAPL")

    def test_multiple_enabled_bundles_merged(self) -> None:
        """Multiple enabled bundles are all included in the union."""
        cfg = _universe(
            symbols=[],
            bundles=[
                _bundle("bundle_a", ["BTC", "ETH"]),
                _bundle("bundle_b", ["SOL", "SUI"]),
            ],
        )
        assert get_scoring_symbols(cfg) == ["BTC", "ETH", "SOL", "SUI"]

    def test_cross_bundle_deduplication(self) -> None:
        """Symbols appearing in multiple bundles are deduplicated."""
        cfg = _universe(
            symbols=[],
            bundles=[
                _bundle("bundle_a", ["BTC", "ETH"]),
                _bundle("bundle_b", ["ETH", "SOL"]),  # ETH duplicated
            ],
        )
        result = get_scoring_symbols(cfg)
        assert result.count("ETH") == 1
        assert result == ["BTC", "ETH", "SOL"]

    def test_only_disabled_bundles_explicit_symbols_returned(self) -> None:
        """If all bundles are disabled, fall back to explicit symbols."""
        cfg = _universe(
            symbols=["BTC"],
            bundles=[_bundle("disabled", ["XRP"], enabled=False)],
        )
        assert get_scoring_symbols(cfg) == ["BTC"]


# ---------------------------------------------------------------------------
# UniverseConfig.active_symbols (integration)
# ---------------------------------------------------------------------------


class TestActiveSymbols:
    """active_symbols() must honour the same merge logic, plus max_size cap."""

    def test_active_symbols_uses_bundle_when_symbols_empty(self) -> None:
        cfg = _universe(
            symbols=[],
            bundles=[_bundle("core", ["BTC", "ETH", "SOL"])],
        )
        assert cfg.active_symbols() == ["BTC", "ETH", "SOL"]

    def test_active_symbols_supplements_bundle_with_explicit(self) -> None:
        cfg = _universe(
            symbols=["HYPE"],
            bundles=[_bundle("core", ["BTC", "ETH"])],
        )
        result = cfg.active_symbols()
        assert "HYPE" in result
        assert result.index("BTC") < result.index("HYPE")

    def test_active_symbols_excludes_disabled_bundle(self) -> None:
        cfg = _universe(
            symbols=[],
            bundles=[
                _bundle("on", ["BTC"], enabled=True),
                _bundle("off", ["DOGE"], enabled=False),
            ],
        )
        assert "DOGE" not in cfg.active_symbols()

    def test_max_size_caps_result(self) -> None:
        cfg = UniverseConfig(
            symbols=["BTC", "ETH", "SOL", "SUI", "HYPE"],
            max_size=3,
        )
        assert len(cfg.active_symbols()) == 3

    def test_default_config_has_no_symbols(self) -> None:
        """Default UniverseConfig ships with empty symbols (bundles drive scoring)."""
        cfg = UniverseConfig()
        assert cfg.symbols == []
