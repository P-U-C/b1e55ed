"""Tests for engine.brain.cts_v2 — continuous CTS scoring."""

from __future__ import annotations

import pytest

from engine.brain.cts_v2 import DEFAULT_CALIBRATION, compute_cts, sigmoid

# ---------------------------------------------------------------------------
# Sigmoid tests
# ---------------------------------------------------------------------------


class TestSigmoid:
    def test_at_center_is_half(self):
        assert sigmoid(10.0, center=10.0) == pytest.approx(0.5)

    def test_above_center_gt_half(self):
        assert sigmoid(15.0, center=10.0) > 0.5

    def test_below_center_lt_half(self):
        assert sigmoid(5.0, center=10.0) < 0.5

    def test_steepness_effect(self):
        gentle = sigmoid(12.0, center=10.0, steepness=0.5)
        steep = sigmoid(12.0, center=10.0, steepness=5.0)
        assert steep > gentle

    def test_overflow_guard_positive(self):
        # Very negative z should not overflow
        result = sigmoid(1000.0, center=0.0, steepness=1.0)
        assert result == 1.0

    def test_overflow_guard_negative(self):
        result = sigmoid(-1000.0, center=0.0, steepness=1.0)
        assert result == 0.0


# ---------------------------------------------------------------------------
# CTS computation
# ---------------------------------------------------------------------------


class TestComputeCTS:
    def test_returns_float_in_range(self):
        features = {
            "rsi_14": 65.0,
            "funding_annualized": 5.0,
            "basis_annualized": 3.0,
            "oi_change_pct": 2.0,
        }
        cts = compute_cts(features)
        assert isinstance(cts, float)
        assert 0.0 <= cts <= 35.0

    def test_gradient_not_binary(self):
        """CTS should never be exactly 0 when features are present (gradient scoring)."""
        features = {
            "rsi_14": 50.0,
            "funding_annualized": 0.0,
            "basis_annualized": 0.0,
        }
        cts = compute_cts(features)
        assert cts > 0.0, "CTS should be > 0 with any features present (sigmoid is never exactly 0)"

    def test_all_neutral_returns_moderate(self):
        """All components at neutral should produce a moderate CTS (5-15 range)."""
        features = {
            "rsi_14": 50.0,
            "funding_annualized": 0.0,
            "basis_annualized": 0.0,
            "oi_change_pct": 0.0,
        }
        cts = compute_cts(features)
        assert 3.0 <= cts <= 18.0, f"Neutral features should produce moderate CTS, got {cts}"

    def test_only_rsi_extreme(self):
        """Only RSI at extreme should contribute."""
        features = {"rsi_14": 80.0}
        cts = compute_cts(features)
        assert cts > 0.0

    def test_only_funding_elevated(self):
        """Only elevated funding should contribute."""
        features = {"funding_annualized": 10.0}
        cts = compute_cts(features)
        assert cts > 0.0

    def test_only_basis_elevated(self):
        """Only elevated basis should contribute."""
        features = {"basis_annualized": 8.0}
        cts = compute_cts(features)
        assert cts > 0.0

    def test_only_oi_pressure(self):
        """Only OI pressure should contribute."""
        features = {"oi_change_pct": 5.0}
        cts = compute_cts(features)
        assert cts > 0.0

    def test_no_features_returns_zero(self):
        cts = compute_cts({})
        assert cts == 0.0

    def test_none_values_skipped(self):
        features = {"rsi_14": None, "funding_annualized": None}
        cts = compute_cts(features)
        assert cts == 0.0

    def test_higher_values_higher_cts(self):
        """More extreme values should produce higher CTS."""
        mild = compute_cts({"rsi_14": 55.0, "funding_annualized": 2.0, "basis_annualized": 2.0})
        extreme = compute_cts({"rsi_14": 80.0, "funding_annualized": 15.0, "basis_annualized": 10.0})
        assert extreme > mild

    def test_calibration_override(self):
        """Custom calibration centers should affect scoring."""
        features = {"rsi_14": 70.0, "funding_annualized": 5.0, "basis_annualized": 5.0}
        cts_default = compute_cts(features, DEFAULT_CALIBRATION)
        cts_tight = compute_cts(features, {"rsi_center": 55.0, "funding_center": 2.0, "basis_center": 2.0})
        # Tighter centers make the same values look more extreme
        assert cts_tight > cts_default

    def test_apr7_cts(self):
        """Apr 7 values: RSI 45, funding 3.65 ann, basis 3.0, no OI."""
        features = {
            "rsi_14": 45.0,
            "funding_annualized": 3.65,
            "basis_annualized": 3.0,
        }
        cts = compute_cts(features, DEFAULT_CALIBRATION)
        # Should be moderate, in the 5-25 range (not 0, not maxed)
        assert 5.0 <= cts <= 25.0, f"Apr 7 CTS should be moderate, got {cts}"

    def test_no_circular_dependency(self):
        """CTS must NOT use regime_score as input."""
        # This is a design test: verify the function signature
        # does not accept regime_score
        import inspect

        sig = inspect.signature(compute_cts)
        params = list(sig.parameters.keys())
        assert "regime_score" not in params
        assert "regime" not in params
