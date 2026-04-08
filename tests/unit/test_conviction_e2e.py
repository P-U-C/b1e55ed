"""End-to-end confidence calculation test for regime v2 + CTS v2.

Key test case from spec: Apr 7 numbers should produce confidence ~0.678
when PCS is ~72 (base ~66.65 + CTS contribution).
"""

from __future__ import annotations

try:
    from datetime import UTC
except ImportError:
    UTC = UTC


from engine.brain.conviction import _confidence_v1, _confidence_v2
from engine.brain.cts_v2 import DEFAULT_CALIBRATION, compute_cts
from engine.brain.regime_v2 import compute_regime_score, regime_label, regime_multiplier

# ---------------------------------------------------------------------------
# Formula integration tests
# ---------------------------------------------------------------------------


class TestConfidenceV2Formula:
    def test_basic_formula(self):
        """confidence = 0.5 + (pcs - 50) / 50 * 0.5 * multiplier"""
        conf = _confidence_v2(pcs=72.0, regime_multiplier=0.809)
        expected = 0.5 + (72.0 - 50.0) / 50.0 * 0.5 * 0.809
        assert abs(conf - expected) < 0.001

    def test_neutral_pcs_gives_half(self):
        conf = _confidence_v2(pcs=50.0, regime_multiplier=0.9)
        assert abs(conf - 0.5) < 0.001

    def test_high_pcs_high_multiplier(self):
        conf = _confidence_v2(pcs=90.0, regime_multiplier=0.95)
        assert conf > 0.8

    def test_clamped_to_range(self):
        assert _confidence_v2(pcs=100.0, regime_multiplier=1.0) <= 0.95
        assert _confidence_v2(pcs=0.0, regime_multiplier=1.0) >= 0.1


# ---------------------------------------------------------------------------
# Apr 7 end-to-end
# ---------------------------------------------------------------------------


class TestApr7EndToEnd:
    """The spec's worked example: funding +0.01%, basis 3%, RSI 45, F&G 8.36."""

    def test_regime_score(self):
        features = {
            "funding_rate": 3.65,  # 0.01% rate * 365
            "basis": 3.0,
            "rsi": 45.0,
            "fear_greed": 8.36,
        }
        score = compute_regime_score(features)
        assert abs(score - (-0.281)) < 0.02, f"Expected ~-0.281, got {score}"

    def test_regime_label(self):
        assert regime_label(-0.281) == "LEAN_BEAR"

    def test_regime_multiplier(self):
        mult = regime_multiplier(-0.281)
        assert abs(mult - 0.809) < 0.01, f"Expected ~0.809, got {mult}"

    def test_cts_is_gradient(self):
        """CTS should produce a non-zero gradient value (not binary 0)."""
        features = {
            "rsi_14": 45.0,
            "funding_annualized": 3.65,
            "basis_annualized": 3.0,
        }
        cts = compute_cts(features, DEFAULT_CALIBRATION)
        assert cts > 0.0, "CTS should be > 0 (not binary threshold)"
        assert cts < 35.0, "CTS should not be maxed"

    def test_confidence_breaks_ceiling(self):
        """With PCS ~72 and multiplier ~0.809, confidence should be ~0.678.

        This is the primary acceptance criterion: confidence >= 0.65.
        """
        # The spec says PCS ~72 after CTS contribution
        pcs = 72.0
        mult = regime_multiplier(-0.281)

        conf = _confidence_v2(pcs=pcs, regime_multiplier=mult)
        assert abs(conf - 0.678) < 0.02, f"Expected ~0.678, got {conf}"
        assert conf >= 0.65, f"Confidence {conf} must break the 0.65 ceiling"

    def test_full_pipeline(self):
        """Full pipeline: regime score -> multiplier -> formula with PCS=72 -> confidence >= 0.65."""
        # Step 1: Regime
        regime_features = {
            "funding_rate": 3.65,
            "basis": 3.0,
            "rsi": 45.0,
            "fear_greed": 8.36,
        }
        score = compute_regime_score(regime_features)
        mult = regime_multiplier(score)
        label = regime_label(score)

        assert label == "LEAN_BEAR"
        assert 0.65 <= mult <= 1.0

        # Step 2: CTS (non-zero, gradient)
        cts_features = {
            "rsi_14": 45.0,
            "funding_annualized": 3.65,
            "basis_annualized": 3.0,
        }
        cts = compute_cts(cts_features, DEFAULT_CALIBRATION)
        assert cts > 0.0

        # Step 3: Confidence with PCS=72 (spec's estimate)
        conf = _confidence_v2(pcs=72.0, regime_multiplier=mult)
        assert conf >= 0.65, f"Pipeline confidence {conf} must be >= 0.65"

    def test_strong_directional_market(self):
        """Spec example: basis 12%, funding -0.05%, RSI 72, F&G 25."""
        regime_features = {
            "funding_rate": -18.25,  # -0.05% * 365
            "basis": 12.0,
            "rsi": 72.0,
            "fear_greed": 25.0,
        }
        score = compute_regime_score(regime_features)
        mult = regime_multiplier(score)

        assert score > 0.2, f"Strong bull signals should give positive score, got {score}"
        assert mult > 0.8, f"Moderate conviction should give high multiplier, got {mult}"

        # With PCS ~78 (spec estimate)
        conf = _confidence_v2(pcs=78.0, regime_multiplier=mult)
        assert conf > 0.7, f"Strong market confidence should be > 0.7, got {conf}"


# ---------------------------------------------------------------------------
# V1 backward compatibility
# ---------------------------------------------------------------------------


class TestV1BackwardCompat:
    def test_v1_still_works(self):
        """V1 confidence function must still work unchanged."""
        conf = _confidence_v1(pcs=66.65, cts=0.0, regime="TRANSITION")
        expected = 0.5 + (66.65 - 50.0) / 50.0 * 0.5 * 0.8
        assert abs(conf - expected) < 0.001

    def test_v1_ceiling(self):
        """V1 with TRANSITION and CTS=0 produces ~0.633."""
        conf = _confidence_v1(pcs=66.65, cts=0.0, regime="TRANSITION")
        assert abs(conf - 0.633) < 0.01, f"V1 ceiling should be ~0.633, got {conf}"


# ---------------------------------------------------------------------------
# Feature flag contract
# ---------------------------------------------------------------------------


class TestFeatureFlag:
    def test_config_has_flag(self):
        from engine.core.config import BrainConfig

        bc = BrainConfig()
        assert hasattr(bc, "use_regime_v2")
        assert bc.use_regime_v2 is False  # default off

    def test_config_has_calibration(self):
        from engine.core.config import BrainConfig, CTSCalibrationConfig

        bc = BrainConfig()
        assert hasattr(bc, "cts_calibration")
        assert isinstance(bc.cts_calibration, CTSCalibrationConfig)
        assert bc.cts_calibration.rsi_center == 60.16
        assert bc.cts_calibration.funding_center == 4.58
        assert bc.cts_calibration.basis_center == 2.33
        assert bc.cts_calibration.oi_roc_center == 3.0
