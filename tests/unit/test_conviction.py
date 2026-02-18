from __future__ import annotations

from datetime import UTC, datetime

from engine.brain.conviction import ConvictionEngine
from engine.core.database import Database
from engine.core.types import FeatureSnapshot
from engine.security.identity import generate_node_identity


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
