"""Tests for engine.brain.regime_v2 — continuous regime detector."""

from __future__ import annotations

import math
from datetime import datetime

try:
    from datetime import UTC
except ImportError:
    UTC = UTC

import pytest

from engine.brain.regime_v2 import (
    RegimeDetectorV2,
    compute_regime_score,
    normalize_basis,
    normalize_fear_greed,
    normalize_funding,
    normalize_rsi,
    regime_label,
    regime_multiplier,
)
from engine.core.database import Database
from engine.core.types import FeatureSnapshot

# ---------------------------------------------------------------------------
# Individual normalizer tests
# ---------------------------------------------------------------------------


class TestNormalizeFunding:
    """High positive funding = crowded longs = bearish (inverted)."""

    def test_positive_funding_is_bearish(self):
        # Annualized 3.65 -> rate 0.01% -> should be negative (bearish)
        result = normalize_funding(3.65)
        assert result < 0, f"Positive funding should produce bearish (negative) score, got {result}"

    def test_negative_funding_is_bullish(self):
        # Negative annualized -> shorts paying -> slightly bullish
        result = normalize_funding(-3.65)
        assert result > 0, f"Negative funding should produce bullish (positive) score, got {result}"

    def test_zero_funding_is_neutral(self):
        result = normalize_funding(0.0)
        assert result == 0.0

    def test_extreme_positive(self):
        result = normalize_funding(36.5)  # ~0.1% daily rate
        assert -1.0 <= result <= 0.0

    def test_apr7_value(self):
        # 0.01% rate -> 3.65 annualized
        result = normalize_funding(3.65)
        assert abs(result - (-0.32)) < 0.02, f"Expected ~-0.32, got {result}"


class TestNormalizeBasis:
    def test_positive_high_basis_is_bullish(self):
        result = normalize_basis(10.0)
        assert result > 0

    def test_low_basis_is_bearish(self):
        result = normalize_basis(1.0)
        assert result < 0

    def test_neutral_at_5pct(self):
        result = normalize_basis(5.0)
        assert abs(result) < 0.01

    def test_apr7_value(self):
        result = normalize_basis(3.0)
        expected = math.tanh(-0.2)  # (3-5)/10 = -0.2
        assert abs(result - expected) < 0.01


class TestNormalizeRSI:
    def test_dead_zone_center(self):
        assert normalize_rsi(50) == 0.0

    def test_dead_zone_boundary_low(self):
        assert normalize_rsi(40) == 0.0

    def test_dead_zone_boundary_high(self):
        assert normalize_rsi(60) == 0.0

    def test_dead_zone_45(self):
        """RSI 45 is in the dead zone."""
        assert normalize_rsi(45) == 0.0

    def test_overbought(self):
        result = normalize_rsi(75)
        assert result > 0
        assert abs(result - 0.5) < 0.01  # (75-60)/30 = 0.5

    def test_oversold(self):
        result = normalize_rsi(25)
        assert result < 0
        assert abs(result - (-0.5)) < 0.01  # (25-40)/30 = -0.5

    def test_extreme_high(self):
        assert normalize_rsi(90) == pytest.approx(1.0)

    def test_extreme_low(self):
        assert normalize_rsi(10) == pytest.approx(-1.0)


class TestNormalizeFearGreed:
    def test_extreme_fear(self):
        result = normalize_fear_greed(0)
        assert result == -1.0

    def test_extreme_greed(self):
        result = normalize_fear_greed(100)
        assert result == 1.0

    def test_neutral(self):
        result = normalize_fear_greed(50)
        assert result == 0.0

    def test_apr7_value(self):
        result = normalize_fear_greed(8.36)
        expected = (8.36 - 50) / 50.0
        assert abs(result - expected) < 0.01


# ---------------------------------------------------------------------------
# Regime score computation
# ---------------------------------------------------------------------------


class TestComputeRegimeScore:
    def test_returns_float_in_range(self):
        features = {"funding_rate": 5.0, "basis": 5.0, "rsi": 50.0, "fear_greed": 50.0}
        score = compute_regime_score(features)
        assert isinstance(score, float)
        assert -1.0 <= score <= 1.0

    def test_all_features_present_apr7(self):
        """Apr 7 test case from spec: funding +0.01% rate (3.65 ann), basis 3%, RSI 45, F&G 8.36."""
        features = {
            "funding_rate": 3.65,  # annualized, = 0.01% rate
            "basis": 3.0,
            "rsi": 45.0,
            "fear_greed": 8.36,
        }
        score = compute_regime_score(features)
        # Spec expects -0.281
        assert abs(score - (-0.281)) < 0.02, f"Expected ~-0.281, got {score}"

    def test_missing_features_graceful(self):
        """Graceful degradation with missing features."""
        # Only funding present
        features = {"funding_rate": 5.0}
        score = compute_regime_score(features)
        assert -1.0 <= score <= 1.0

    def test_no_features_returns_zero(self):
        score = compute_regime_score({})
        assert score == 0.0

    def test_none_values_skipped(self):
        features = {"funding_rate": None, "basis": 5.0, "rsi": None, "fear_greed": None}
        score = compute_regime_score(features)
        # Only basis contributes: normalize_basis(5.0) ≈ 0.0
        assert abs(score) < 0.05

    def test_strong_bull_signal(self):
        """High basis, negative funding (shorts paying), high RSI, high greed."""
        features = {
            "funding_rate": -18.25,  # -0.05% rate annualized
            "basis": 12.0,
            "rsi": 72.0,
            "fear_greed": 75.0,
        }
        score = compute_regime_score(features)
        assert score > 0.3, f"Strong bull signals should produce positive score, got {score}"

    def test_strong_bear_signal(self):
        """Low basis, high positive funding (crowded longs), low RSI, extreme fear."""
        features = {
            "funding_rate": 18.25,  # 0.05% rate annualized, crowded longs
            "basis": 1.0,
            "rsi": 25.0,
            "fear_greed": 10.0,
        }
        score = compute_regime_score(features)
        assert score < -0.3, f"Strong bear signals should produce negative score, got {score}"


# ---------------------------------------------------------------------------
# Regime multiplier
# ---------------------------------------------------------------------------


class TestRegimeMultiplier:
    def test_ambiguous_floor(self):
        mult = regime_multiplier(0.0)
        assert mult == 0.65

    def test_moderate(self):
        mult = regime_multiplier(0.5)
        assert abs(mult - 0.862) < 0.02  # 0.65 + sqrt(0.5)*0.30

    def test_strong(self):
        mult = regime_multiplier(0.7)
        expected = 0.65 + math.sqrt(0.7) * 0.30
        assert abs(mult - expected) < 0.01

    def test_extreme(self):
        mult = regime_multiplier(1.0)
        assert mult == pytest.approx(0.95)

    def test_range(self):
        for score in [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0, -0.5, -1.0]:
            mult = regime_multiplier(score)
            assert 0.65 <= mult <= 1.0, f"Multiplier {mult} out of range for score {score}"

    def test_apr7_multiplier(self):
        """Score -0.281 should give multiplier ~0.809."""
        mult = regime_multiplier(-0.281)
        assert abs(mult - 0.809) < 0.01, f"Expected ~0.809, got {mult}"


# ---------------------------------------------------------------------------
# Regime label
# ---------------------------------------------------------------------------


class TestRegimeLabel:
    def test_bull(self):
        assert regime_label(0.6) == "BULL"

    def test_lean_bull(self):
        assert regime_label(0.3) == "LEAN_BULL"

    def test_neutral(self):
        assert regime_label(0.0) == "NEUTRAL"

    def test_lean_bear(self):
        assert regime_label(-0.3) == "LEAN_BEAR"

    def test_bear(self):
        assert regime_label(-0.6) == "BEAR"

    def test_apr7_label(self):
        """Score -0.281 -> LEAN_BEAR."""
        assert regime_label(-0.281) == "LEAN_BEAR"

    def test_boundaries(self):
        assert regime_label(0.5) == "BULL"
        assert regime_label(0.2) == "LEAN_BULL"
        assert regime_label(-0.19) == "NEUTRAL"
        assert regime_label(-0.2) == "LEAN_BEAR"  # -0.2 is NOT > -0.2
        assert regime_label(-0.49) == "LEAN_BEAR"
        assert regime_label(-0.5) == "BEAR"  # -0.5 is NOT > -0.5

    def test_no_transition_or_crisis(self):
        """TRANSITION and CRISIS labels are retired."""
        for score_val in [-1.0, -0.7, -0.3, 0.0, 0.3, 0.7, 1.0]:
            label = regime_label(score_val)
            assert label not in ("TRANSITION", "CRISIS"), f"Retired label {label} at score {score_val}"


# ---------------------------------------------------------------------------
# Detector class integration
# ---------------------------------------------------------------------------


class TestRegimeDetectorV2:
    def _make_snapshot(self, features: dict) -> FeatureSnapshot:
        return FeatureSnapshot(
            cycle_id="test",
            symbol="BTC",
            ts=datetime.now(tz=UTC),
            features=features,
            source_event_ids=[],
            regime=None,
            version="v2",
        )

    def test_detect_for_asset(self, temp_dir):
        db = Database(temp_dir / "brain.db")
        detector = RegimeDetectorV2(db)

        snap = self._make_snapshot(
            {
                "tradfi": {"funding_annualized": 3.65, "basis_annualized": 3.0},
                "technical": {"rsi_14": 45.0},
                "social": {"fear_greed": 8.36},
            }
        )
        result = detector.detect_for_asset(snap)

        assert -1.0 <= result.score <= 1.0
        assert 0.65 <= result.multiplier <= 1.0
        assert result.label in ("BULL", "LEAN_BULL", "NEUTRAL", "LEAN_BEAR", "BEAR")

    def test_detect_backward_compat(self, temp_dir):
        """detect() returns RegimeResult for orchestrator compatibility."""
        db = Database(temp_dir / "brain.db")
        detector = RegimeDetectorV2(db)

        snap = self._make_snapshot(
            {
                "tradfi": {"funding_annualized": 5.0, "basis_annualized": 5.0},
                "technical": {"rsi_14": 50.0},
                "social": {"fear_greed": 50.0},
            }
        )
        result = detector.detect(btc_snapshot=snap)
        assert hasattr(result, "state")
        assert hasattr(result, "changed")
        assert hasattr(result, "previous")

    def test_emit_forecast_event(self, temp_dir):
        """detect_for_asset should emit FORECAST_V1 event."""
        db = Database(temp_dir / "brain.db")
        detector = RegimeDetectorV2(db)

        snap = self._make_snapshot(
            {
                "tradfi": {"funding_annualized": 3.65, "basis_annualized": 3.0},
                "technical": {"rsi_14": 45.0},
                "social": {"fear_greed": 8.36},
            }
        )
        detector.detect_for_asset(snap)

        from engine.core.events import EventType

        events = db.get_events(event_type=EventType.FORECAST_V1, limit=10)
        assert len(events) >= 1
        payload = events[0].payload
        assert payload.get("type") == "regime_v2"
        assert "score" in payload
        assert "multiplier" in payload

    def test_empty_snapshot(self, temp_dir):
        """Empty features -> neutral."""
        db = Database(temp_dir / "brain.db")
        detector = RegimeDetectorV2(db)

        snap = self._make_snapshot({})
        result = detector.detect_for_asset(snap)
        assert result.score == 0.0
        assert result.label == "NEUTRAL"
