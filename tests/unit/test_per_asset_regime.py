from __future__ import annotations

from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017


from engine.brain.regime import RegimeDetector
from engine.brain.synthesis import SynthesisResult, VectorSynthesis
from engine.core.database import Database
from engine.core.events import EventType
from engine.core.types import FeatureSnapshot


def _snapshot(symbol: str, features: dict[str, dict[str, float]]) -> FeatureSnapshot:
    return FeatureSnapshot(
        cycle_id="cycle-1",
        symbol=symbol,
        ts=datetime.now(tz=UTC),
        features=features,
        source_event_ids=[],
        regime=None,
        version="v2",
    )


def test_detect_for_asset_bull(temp_dir):
    db = Database(temp_dir / "brain.db")
    detector = RegimeDetector(db)

    snap = _snapshot(
        "ETH",
        {
            "technical": {"rsi_14": 62.0, "ema_20": 2550.0, "ema_50": 2480.0},
            "tradfi": {"funding_annualized": 0.02, "basis_annualized": 4.2},
        },
    )

    result = detector.detect_for_asset(snap)
    assert result.state.regime == "BULL"


def test_detect_for_asset_bear(temp_dir):
    db = Database(temp_dir / "brain.db")
    detector = RegimeDetector(db)

    snap = _snapshot(
        "SOL",
        {
            "technical": {"rsi_14": 40.0, "ema_20": 130.0, "ema_50": 140.0},
            "tradfi": {"funding_annualized": -0.01, "basis_annualized": 1.8},
        },
    )

    result = detector.detect_for_asset(snap)
    assert result.state.regime in {"BEAR", "TRANSITION"}


def test_detect_for_asset_no_features(temp_dir):
    db = Database(temp_dir / "brain.db")
    detector = RegimeDetector(db)

    # Seed last known global regime to exercise fallback behavior.
    global_bull = _snapshot(
        "BTC",
        {
            "technical": {"rsi_14": 56.0},
            "tradfi": {"funding_annualized": 10.0, "basis_annualized": 5.0},
            "social": {"fear_greed": 50.0},
        },
    )
    detector.detect(as_of=global_bull.ts, btc_snapshot=global_bull)

    empty = _snapshot("ETH", {})
    result = detector.detect_for_asset(empty)

    assert result.state.regime == "BULL"
    assert result.previous == "BULL"


def test_synthesis_result_has_regime_tag():
    result = SynthesisResult(
        snapshot=_snapshot("BTC", {}),
        domain_scores={},
        weights_used={},
        weighted_score=0.0,
    )

    assert result.regime_tag == "unknown"


def test_synthesize_with_regime_returns_regime_tag(test_config, temp_dir):
    db = Database(temp_dir / "brain.db")
    now = datetime.now(tz=UTC)

    db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "ETH", "rsi_14": 63.0, "ema_20": 2550.0, "ema_50": 2480.0},
        ts=now,
    )
    db.append_event(
        event_type=EventType.SIGNAL_TRADFI_V1,
        payload={"symbol": "ETH", "funding_annualized": 0.02, "basis_annualized": 4.1},
        ts=now,
    )

    synth = VectorSynthesis(test_config, db)
    detector = RegimeDetector(db)

    result = synth.synthesize_with_regime(
        cycle_id="cycle-with-regime",
        symbol="ETH",
        as_of=now,
        quality_adjustment=None,
        regime_detector=detector,
    )

    assert result.regime_tag != "unknown"
    assert result.regime_tag == "BULL"
