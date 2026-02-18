from __future__ import annotations

from datetime import UTC, datetime

from engine.brain.regime import RegimeDetector
from engine.core.database import Database
from engine.core.types import FeatureSnapshot


def _snap(regime_inputs: dict[str, dict[str, float]]) -> FeatureSnapshot:
    return FeatureSnapshot(
        cycle_id="c",
        symbol="BTC",
        ts=datetime.now(tz=UTC),
        features=regime_inputs,
        source_event_ids=[],
        regime=None,
        version="v2",
    )


def test_regime_classifies_bull_bear_crisis_transition(temp_dir):
    db = Database(temp_dir / "brain.db")
    det = RegimeDetector(db)

    bull = _snap(
        {
            "technical": {"rsi_14": 55.0},
            "tradfi": {"funding_annualized": 10.0, "basis_annualized": 5.0},
            "social": {"fear_greed": 50.0},
        }
    )
    r1 = det.detect(as_of=datetime.now(tz=UTC), btc_snapshot=bull)
    assert r1.state.regime == "BULL"

    bear = _snap(
        {
            "technical": {"rsi_14": 25.0},
            "tradfi": {"funding_annualized": -1.0, "basis_annualized": 1.5},
            "social": {"fear_greed": 20.0},
        }
    )
    r2 = det.detect(as_of=datetime.now(tz=UTC), btc_snapshot=bear)
    assert r2.state.regime == "BEAR"

    crisis = _snap(
        {
            "tradfi": {"funding_annualized": -15.0, "basis_annualized": 0.5},
            "social": {"fear_greed": 10.0},
        }
    )
    r3 = det.detect(as_of=datetime.now(tz=UTC), btc_snapshot=crisis)
    assert r3.state.regime == "CRISIS"

    transition = _snap({"technical": {"rsi_14": 50.0}})
    r4 = det.detect(as_of=datetime.now(tz=UTC), btc_snapshot=transition)
    assert r4.state.regime == "TRANSITION"
