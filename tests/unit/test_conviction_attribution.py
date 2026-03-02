from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    UTC = UTC  # noqa: N806


import pytest

from engine.brain.conviction import ConvictionEngine
from engine.core.database import Database
from engine.core.types import FeatureSnapshot
from engine.security.identity import generate_node_identity


def _build_result(*, engine: ConvictionEngine, cycle_id: str, symbol: str = "BTC"):
    snapshot = FeatureSnapshot(
        cycle_id=cycle_id,
        symbol=symbol,
        ts=datetime.now(tz=UTC),
        features={
            "tradfi": {"funding_annualized": 20.0, "basis_annualized": 4.0},
            "technical": {"rsi_14": 55.0},
        },
        source_event_ids=["evt-1"],
        regime="BULL",
        version="v2",
    )

    synthesis = SimpleNamespace(
        snapshot=snapshot,
        domain_scores={"tradfi": 0.8, "technical": 0.6},
        weights_used={"tradfi": 0.6, "technical": 0.4},
        weighted_score=0.72,
    )

    return engine.compute(synthesis=synthesis, regime="BULL", as_of=datetime.now(tz=UTC))


def test_emit_persists_producer_attribution_fields(test_config, temp_dir, monkeypatch):
    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "test")
    ident = generate_node_identity()

    db = Database(temp_dir / "brain.db")
    eng = ConvictionEngine(test_config, db, node_id=ident.node_id)

    result = _build_result(engine=eng, cycle_id="cycle-attr")
    eng.emit(
        result,
        cycle_id="cycle-attr",
        producer_name="producer.social",
        event_id="signal-social-123",
        contribution_weight=0.6,
    )

    rows = db.conn.execute(
        """
        SELECT producer_name, event_id, contribution_weight
        FROM conviction_log
        WHERE cycle_id = ?
        """,
        ("cycle-attr",),
    ).fetchall()

    assert len(rows) == 2
    assert all(str(r["producer_name"]) == "producer.social" for r in rows)
    assert all(str(r["event_id"]) == "signal-social-123" for r in rows)
    assert all(float(r["contribution_weight"]) == pytest.approx(0.6) for r in rows)


def test_forecast_attribution_table_exists_and_accepts_row(temp_dir):
    db = Database(temp_dir / "brain.db")

    with db.conn:
        db.conn.execute(
            """
            INSERT INTO forecast_attribution (
                forecast_id,
                conviction_id,
                position_id,
                contribution_weight,
                disposition
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("forecast-1", "conviction-1", None, 0.75, "included"),
        )

    row = db.conn.execute(
        """
        SELECT forecast_id, conviction_id, position_id, contribution_weight, disposition
        FROM forecast_attribution
        WHERE forecast_id = ?
        """,
        ("forecast-1",),
    ).fetchone()

    assert row is not None
    assert str(row["forecast_id"]) == "forecast-1"
    assert str(row["conviction_id"]) == "conviction-1"
    assert row["position_id"] is None
    assert float(row["contribution_weight"]) == pytest.approx(0.75)
    assert str(row["disposition"]) == "included"


def test_emit_defaults_keep_backward_compatibility(test_config, temp_dir, monkeypatch):
    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "test")
    ident = generate_node_identity()

    db = Database(temp_dir / "brain.db")
    eng = ConvictionEngine(test_config, db, node_id=ident.node_id)

    result = _build_result(engine=eng, cycle_id="cycle-default")
    eng.emit(result, cycle_id="cycle-default")

    rows = db.conn.execute(
        """
        SELECT producer_name, event_id, contribution_weight
        FROM conviction_log
        WHERE cycle_id = ?
        """,
        ("cycle-default",),
    ).fetchall()

    assert len(rows) == 2
    assert all(str(r["producer_name"]) == "" for r in rows)
    assert all(str(r["event_id"]) == "" for r in rows)
    assert all(float(r["contribution_weight"]) == pytest.approx(1.0) for r in rows)


def test_feature_key_populated_in_conviction_log(test_config, temp_dir, monkeypatch):
    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "test")
    ident = generate_node_identity()

    db = Database(temp_dir / "brain.db")
    eng = ConvictionEngine(test_config, db, node_id=ident.node_id)

    result = _build_result(engine=eng, cycle_id="cycle-features")
    eng.emit(result, cycle_id="cycle-features")

    rows = db.conn.execute(
        """
        SELECT domain, feature_key, feature_value
        FROM conviction_log
        WHERE cycle_id = ?
        ORDER BY domain
        """,
        ("cycle-features",),
    ).fetchall()

    assert len(rows) == 2
    observed = {str(r["domain"]): (r["feature_key"], float(r["feature_value"]) if r["feature_value"] is not None else None) for r in rows}
    assert observed["technical"] == ("rsi_14", pytest.approx(55.0))
    assert observed["tradfi"] == ("funding_annualized", pytest.approx(20.0))


def test_feature_key_null_when_no_snapshot(test_config, temp_dir, monkeypatch):
    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "test")
    ident = generate_node_identity()

    db = Database(temp_dir / "brain.db")
    eng = ConvictionEngine(test_config, db, node_id=ident.node_id)

    result = replace(_build_result(engine=eng, cycle_id="cycle-null-features"), snapshot=None)
    eng.emit(result, cycle_id="cycle-null-features")

    rows = db.conn.execute(
        """
        SELECT feature_key, feature_value
        FROM conviction_log
        WHERE cycle_id = ?
        """,
        ("cycle-null-features",),
    ).fetchall()

    assert len(rows) == 2
    assert all(r["feature_key"] is None for r in rows)
    assert all(r["feature_value"] is None for r in rows)


def test_primary_feature_is_max_absolute_value(test_config, temp_dir, monkeypatch):
    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "test")
    ident = generate_node_identity()

    db = Database(temp_dir / "brain.db")
    eng = ConvictionEngine(test_config, db, node_id=ident.node_id)

    base = _build_result(engine=eng, cycle_id="cycle-primary-feature")
    custom_snapshot = FeatureSnapshot(
        cycle_id="cycle-primary-feature",
        symbol="BTC",
        ts=datetime.now(tz=UTC),
        features={"tradfi": {"rsi": 0.3, "macd": 0.8, "ema": -0.9}},
        source_event_ids=["evt-1"],
        regime="BULL",
        version="v2",
    )
    result = replace(
        base,
        domain_scores={"tradfi": base.domain_scores["tradfi"]},
        weights_used={"tradfi": base.weights_used["tradfi"]},
        snapshot=custom_snapshot,
    )

    eng.emit(result, cycle_id="cycle-primary-feature")

    row = db.conn.execute(
        """
        SELECT feature_key, feature_value
        FROM conviction_log
        WHERE cycle_id = ? AND domain = 'tradfi'
        """,
        ("cycle-primary-feature",),
    ).fetchone()

    assert row is not None
    assert str(row["feature_key"]) == "ema"
    assert float(row["feature_value"]) == pytest.approx(-0.9)
