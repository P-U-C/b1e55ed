from __future__ import annotations

from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017


import pytest

from engine.brain.conviction import ConvictionEngine, _confidence_v1
from engine.core.database import Database
from engine.core.types import FeatureSnapshot
from engine.security.identity import generate_node_identity


def _build_engine(test_config, temp_dir, monkeypatch) -> ConvictionEngine:
    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "test")
    ident = generate_node_identity()
    db = Database(temp_dir / "brain.db")
    return ConvictionEngine(test_config, db, node_id=ident.node_id)


def _build_synthesis(*, weighted_score: float, features: dict[str, dict[str, float]]):
    snap = FeatureSnapshot(
        cycle_id="c",
        symbol="BTC",
        ts=datetime.now(tz=UTC),
        features=features,
        source_event_ids=[],
        regime=None,
        version="v2",
    )

    class _Synth:
        pass

    synth = _Synth()
    synth.snapshot = snap
    synth.domain_scores = {domain: 1.0 for domain in features}
    synth.weights_used = {domain: (1.0 / len(features) if features else 0.0) for domain in features}
    synth.weighted_score = weighted_score
    return synth


def test_pcs_calculation_and_cts_auto_trigger_at_pcs_gt_75(test_config, temp_dir, monkeypatch):
    # Identity requires password env; set for test.
    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "test")
    ident = generate_node_identity()

    db = Database(temp_dir / "brain.db")
    eng = ConvictionEngine(test_config, db, node_id=ident.node_id)

    # Build a synthesis-like object with very high weighted score.
    snap = FeatureSnapshot(
        cycle_id="c",
        symbol="BTC",
        ts=datetime.now(tz=UTC),
        features={"tradfi": {"funding_annualized": 35.0}, "technical": {"rsi_14": 75.0}},
        source_event_ids=[],
        regime=None,
        version="v2",
    )

    class _Synth:
        snapshot = snap
        domain_scores = {"tradfi": 1.0, "technical": 1.0}
        weights_used = {"tradfi": 0.5, "technical": 0.5}
        weighted_score = 0.9

    res = eng.compute(synthesis=_Synth(), regime="BULL", as_of=datetime.now(tz=UTC))
    assert res.pcs > 75.0
    assert res.cts > 0.0  # auto-triggered
    assert 0.0 <= res.final_conviction <= 100.0


def test_counter_thesis_fires_below_pcs_75(test_config, temp_dir, monkeypatch) -> None:
    eng = _build_engine(test_config, temp_dir, monkeypatch)
    synth = _build_synthesis(
        weighted_score=0.60,
        features={"technical": {"rsi_14": 75.0}},
    )

    res = eng.compute(synthesis=synth, regime="BULL", as_of=datetime.now(tz=UTC))

    assert res.pcs < 75.0
    assert res.cts > 0.0


def test_counter_thesis_fires_above_pcs_75(test_config, temp_dir, monkeypatch) -> None:
    eng = _build_engine(test_config, temp_dir, monkeypatch)
    synth = _build_synthesis(
        weighted_score=0.80,
        features={"technical": {"rsi_14": 75.0}},
    )

    res = eng.compute(synthesis=synth, regime="BULL", as_of=datetime.now(tz=UTC))

    assert res.pcs > 75.0
    assert res.cts > 0.0


def test_regime_cap_bear(test_config, temp_dir, monkeypatch) -> None:
    eng = _build_engine(test_config, temp_dir, monkeypatch)
    synth = _build_synthesis(
        weighted_score=1.0,
        features={"technical": {"rsi_14": 50.0}},
    )

    res = eng.compute(synthesis=synth, regime="BEAR", as_of=datetime.now(tz=UTC))

    assert res.score.magnitude == pytest.approx(7.0)
    assert res.capped_by_regime is True
    assert res.pre_cap_magnitude == pytest.approx(10.0)


def test_regime_cap_crisis(test_config, temp_dir, monkeypatch) -> None:
    eng = _build_engine(test_config, temp_dir, monkeypatch)
    synth = _build_synthesis(
        weighted_score=1.0,
        features={"technical": {"rsi_14": 50.0}},
    )

    res = eng.compute(synthesis=synth, regime="CRISIS", as_of=datetime.now(tz=UTC))

    assert res.score.magnitude == pytest.approx(4.0)
    assert res.capped_by_regime is True


def test_regime_cap_bull_no_cap(test_config, temp_dir, monkeypatch) -> None:
    eng = _build_engine(test_config, temp_dir, monkeypatch)
    synth = _build_synthesis(
        weighted_score=1.0,
        features={"technical": {"rsi_14": 50.0}},
    )

    res = eng.compute(synthesis=synth, regime="BULL", as_of=datetime.now(tz=UTC))

    assert res.score.magnitude == pytest.approx(10.0)
    assert res.capped_by_regime is False
    assert res.pre_cap_magnitude is None


def test_capped_by_regime_flag_set(test_config, temp_dir, monkeypatch) -> None:
    eng = _build_engine(test_config, temp_dir, monkeypatch)
    synth = _build_synthesis(
        weighted_score=0.95,
        features={"technical": {"rsi_14": 50.0}},
    )

    res = eng.compute(synthesis=synth, regime="TRANSITION", as_of=datetime.now(tz=UTC))

    assert res.capped_by_regime is True
    assert res.pre_cap_magnitude is not None
    assert res.pre_cap_magnitude > res.score.magnitude


def test_confidence_bull_high_pcs() -> None:
    confidence = _confidence_v1(pcs=80.0, cts=10.0, regime="BULL")
    assert confidence == pytest.approx(0.75)


def test_confidence_chop_dampens() -> None:
    bull = _confidence_v1(pcs=80.0, cts=10.0, regime="BULL")
    chop = _confidence_v1(pcs=80.0, cts=10.0, regime="CHOP")

    assert chop == pytest.approx(0.66)
    assert chop < bull


def test_confidence_high_cts_penalty() -> None:
    low_cts = _confidence_v1(pcs=80.0, cts=10.0, regime="BULL")
    high_cts = _confidence_v1(pcs=80.0, cts=80.0, regime="BULL")

    assert high_cts == pytest.approx(0.4)
    assert high_cts < low_cts


def test_confidence_bear_regime() -> None:
    bull = _confidence_v1(pcs=80.0, cts=10.0, regime="BULL")
    bear = _confidence_v1(pcs=80.0, cts=10.0, regime="BEAR")
    chop = _confidence_v1(pcs=80.0, cts=10.0, regime="CHOP")

    assert bear == pytest.approx(0.705)
    assert chop < bear < bull


def test_confidence_clamp_min() -> None:
    confidence = _confidence_v1(pcs=-1000.0, cts=10000.0, regime="CHOP")
    assert confidence == 0.1


@pytest.mark.parametrize("regime", ["BULL", "BEAR", "CHOP", "TRANSITION", "CRISIS", None])
def test_confidence_always_clamped_to_contract_bounds(regime: str | None) -> None:
    for pcs in range(-200, 301, 25):
        for cts in range(-100, 401, 25):
            confidence = _confidence_v1(pcs=float(pcs), cts=float(cts), regime=regime)
            assert 0.1 <= confidence <= 0.95
