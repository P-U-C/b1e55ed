from __future__ import annotations

import sqlite3
from datetime import datetime
from types import SimpleNamespace

import pytest

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from engine.brain.hierarchy import (
    MAX_MULTIPLIER,
    MIN_MULTIPLIER,
    HierarchyEngine,
    _brier_to_multiplier,
)
from engine.brain.synthesis import VectorSynthesis
from engine.core.database import Database
from engine.core.events import EventType


def _seed_calibration(
    db: Database,
    *,
    producer: str,
    brier_scores: list[float],
    asset: str = "BTC",
    regime: str = "BULL",
) -> None:
    now = datetime.now(tz=UTC).isoformat()
    with db.conn:
        for idx, brier in enumerate(brier_scores):
            db.conn.execute(
                """
                INSERT INTO forecast_calibration (
                    forecast_id,
                    producer_name,
                    asset,
                    regime,
                    horizon,
                    direction,
                    confidence,
                    calibrated,
                    outcome,
                    brier_score,
                    emitted_at,
                    resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{producer}-f{idx}",
                    producer,
                    asset,
                    regime,
                    "4h",
                    "bullish",
                    0.7,
                    0,
                    1.0,
                    float(brier),
                    now,
                    now,
                ),
            )


def _seed_signal_accepted(db: Database, *, producer_id: str, domain: str) -> None:
    db.append_event(
        event_type=EventType.SIGNAL_ACCEPTED_V1,
        payload={
            "trade_id": "t-1",
            "producer_id": producer_id,
            "domain": domain,
            "signal_event_id": f"sig-{producer_id}",
            "contribution_weight": 1.0,
            "direction": "bullish",
            "confidence": 0.7,
        },
        ts=datetime.now(tz=UTC),
    )


def test_brier_to_multiplier_thresholds() -> None:
    assert _brier_to_multiplier(0.05) == 1.5
    assert _brier_to_multiplier(0.25) == 1.0
    assert _brier_to_multiplier(0.40) == 0.70


def test_compute_empty_db_graceful_degradation(temp_dir) -> None:
    db = Database(temp_dir / "brain.db")
    engine = HierarchyEngine(db)

    result = engine.compute(
        symbol="BTC",
        regime="BULL",
        producer_domain_map={"pa": "technical", "pb": "onchain"},
    )

    assert set(result.multipliers.keys()) == {"technical", "onchain"}
    assert all(mult == pytest.approx(1.0) for mult in result.multipliers.values())


def test_compute_good_brier_data_boosts_multiplier(temp_dir) -> None:
    db = Database(temp_dir / "brain.db")
    _seed_calibration(db, producer="tech.alpha", brier_scores=[0.05] * 6, asset="BTC", regime="BULL")

    engine = HierarchyEngine(db)
    result = engine.compute(
        symbol="BTC",
        regime="BULL",
        producer_domain_map={"tech.alpha": "technical"},
    )

    assert result.multipliers["technical"] > 1.0


def test_compute_poor_brier_data_reduces_multiplier(temp_dir) -> None:
    db = Database(temp_dir / "brain.db")
    _seed_calibration(db, producer="tech.beta", brier_scores=[0.40] * 6, asset="BTC", regime="BULL")

    engine = HierarchyEngine(db)
    result = engine.compute(
        symbol="BTC",
        regime="BULL",
        producer_domain_map={"tech.beta": "technical"},
    )

    assert result.multipliers["technical"] < 1.0


def test_correlation_penalty_no_table_returns_zero() -> None:
    db = SimpleNamespace(conn=sqlite3.connect(":memory:"))
    engine = HierarchyEngine(db)

    penalty = engine._correlation_penalty(
        domain="technical",
        producer_domain_map={"pa": "technical", "pb": "social"},
        symbol="BTC",
        regime="BULL",
    )

    assert penalty == 0.0


def test_correlation_penalty_high_corr_returns_scaled_penalty(temp_dir) -> None:
    db = Database(temp_dir / "brain.db")
    with db.conn:
        db.conn.execute(
            """
            INSERT INTO producer_correlation (
                producer_a,
                producer_b,
                asset,
                regime,
                pearson_r,
                sample_count,
                window_days,
                last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            ("pa", "pb", "ALL", "unknown", 0.8, 12, 30),
        )

    engine = HierarchyEngine(db)
    penalty = engine._correlation_penalty(
        domain="technical",
        producer_domain_map={"pa": "technical", "pb": "social"},
        symbol="BTC",
        regime="BULL",
    )

    assert penalty == pytest.approx(0.4)


def test_compute_multiplier_clamped_to_bounds(temp_dir, monkeypatch) -> None:
    db = Database(temp_dir / "brain.db")
    engine = HierarchyEngine(db)

    monkeypatch.setattr(engine, "_producer_reliability", lambda *_args, **_kwargs: 99.0)
    monkeypatch.setattr(engine, "_asset_fit", lambda *_args, **_kwargs: 99.0)
    monkeypatch.setattr(engine, "_regime_fit", lambda *_args, **_kwargs: 99.0)
    monkeypatch.setattr(engine, "_correlation_penalty", lambda **_kwargs: -10.0)
    high = engine.compute(symbol="BTC", regime="BULL", producer_domain_map={"pa": "technical"})
    assert high.multipliers["technical"] == MAX_MULTIPLIER

    monkeypatch.setattr(engine, "_producer_reliability", lambda *_args, **_kwargs: -99.0)
    monkeypatch.setattr(engine, "_asset_fit", lambda *_args, **_kwargs: -99.0)
    monkeypatch.setattr(engine, "_regime_fit", lambda *_args, **_kwargs: -99.0)
    monkeypatch.setattr(engine, "_correlation_penalty", lambda **_kwargs: 99.0)
    low = engine.compute(symbol="BTC", regime="BULL", producer_domain_map={"pa": "technical"})
    assert low.multipliers["technical"] == MIN_MULTIPLIER


def test_synthesize_hierarchy_re_normalizes_weights_and_populates_factors(test_config, temp_dir) -> None:
    db = Database(temp_dir / "brain.db")
    now = datetime.now(tz=UTC)

    db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "BTC", "rsi_14": 35.0, "trend_strength": 0.8},
        ts=now,
    )
    db.append_event(
        event_type=EventType.SIGNAL_SOCIAL_V1,
        payload={"symbol": "BTC", "score": 2.0, "direction": "bullish", "source_count": 5},
        ts=now,
    )

    _seed_signal_accepted(db, producer_id="tech.alpha", domain="technical")
    _seed_signal_accepted(db, producer_id="social.alpha", domain="social")

    _seed_calibration(db, producer="tech.alpha", brier_scores=[0.05] * 6, asset="BTC", regime="BULL")
    _seed_calibration(db, producer="social.alpha", brier_scores=[0.40] * 6, asset="BTC", regime="BULL")

    result = VectorSynthesis(test_config, db).synthesize(cycle_id="c-h", symbol="BTC", as_of=now)

    assert sum(result.weights_used.values()) == pytest.approx(1.0)
    assert result.hierarchy_factors
    assert "technical" in result.hierarchy_factors
    assert "social" in result.hierarchy_factors


def test_synthesis_result_hierarchy_factors_empty_when_hierarchy_skipped(test_config, temp_dir) -> None:
    db = Database(temp_dir / "brain.db")
    now = datetime.now(tz=UTC)

    db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": "BTC", "rsi_14": 35.0, "trend_strength": 0.8},
        ts=now,
    )

    result = VectorSynthesis(test_config, db).synthesize(cycle_id="c-no-h", symbol="BTC", as_of=now)
    assert result.hierarchy_factors == {}
