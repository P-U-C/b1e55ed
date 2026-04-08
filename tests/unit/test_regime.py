from __future__ import annotations

from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017


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


def test_regime_tiebreaker_bear(temp_dir):
    """2 bull + 2 bear with fear_greed < 25 should break tie to BEAR."""
    db = Database(temp_dir / "brain.db")
    det = RegimeDetector(db)

    # funding+RSI vote BULL(2), basis+fear_greed vote BEAR(2)
    deadlock = _snap(
        {
            "technical": {"rsi_14": 55.0},
            "tradfi": {"funding_annualized": 10.0, "basis_annualized": 1.5},
            "social": {"fear_greed": 8.36},
        }
    )
    r = det.detect(as_of=datetime.now(tz=UTC), btc_snapshot=deadlock)
    assert r.state.regime == "BEAR"


def test_regime_tiebreaker_bull(temp_dir):
    """2 bull + 2 bear with fear_greed > 40 should break tie to BULL."""
    db = Database(temp_dir / "brain.db")
    det = RegimeDetector(db)

    # rsi < 30 + basis < 2 vote BEAR(2), funding + fng vote BULL(2)
    deadlock = _snap(
        {
            "technical": {"rsi_14": 25.0},
            "tradfi": {"funding_annualized": 10.0, "basis_annualized": 1.5},
            "social": {"fear_greed": 50.0},
        }
    )
    r = det.detect(as_of=datetime.now(tz=UTC), btc_snapshot=deadlock)
    assert r.state.regime == "BULL"


def test_regime_majority_bull_without_full_consensus(temp_dir):
    """2 bull > 1 bear should classify BULL (no longer needs 3/4)."""
    db = Database(temp_dir / "brain.db")
    det = RegimeDetector(db)

    snap = _snap(
        {
            "technical": {"rsi_14": 55.0},
            "tradfi": {"funding_annualized": 10.0, "basis_annualized": 1.5},
            "social": {"fear_greed": 30.0},
        }
    )
    r = det.detect(as_of=datetime.now(tz=UTC), btc_snapshot=snap)
    assert r.state.regime == "BULL"
