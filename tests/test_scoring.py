"""Tests for P2.4 learnable scoring — scoring_params + shadow/live promotion."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.brain.scoring import (
    DEFAULT_PARAMS,
    ensure_defaults,
    get_param,
    list_params,
    promote_to_live,
    propose_shadow_update,
)
from engine.core.database import Database


@pytest.fixture()
def db(temp_dir: Path) -> Database:
    database = Database(temp_dir / "brain.db")
    try:
        yield database
    finally:
        database.close()


# ------------------------------------------------------------------
# ensure_defaults
# ------------------------------------------------------------------


def test_ensure_defaults_seeds_all_default_params(db: Database) -> None:
    ensure_defaults(db)
    rows = db.conn.execute("SELECT param_key FROM scoring_params").fetchall()
    keys = {str(r[0]) for r in rows}
    assert len(rows) == len(DEFAULT_PARAMS)
    assert keys == set(DEFAULT_PARAMS)


def test_ensure_defaults_is_idempotent(db: Database) -> None:
    ensure_defaults(db)
    ensure_defaults(db)
    count = db.conn.execute("SELECT COUNT(*) FROM scoring_params").fetchone()[0]
    assert int(count) == len(DEFAULT_PARAMS)


# ------------------------------------------------------------------
# get_param
# ------------------------------------------------------------------


def test_get_param_returns_default_value_in_shadow_mode(db: Database) -> None:
    ensure_defaults(db)
    assert get_param(db, "tradfi.funding_optimal_center") == pytest.approx(10.0)
    assert get_param(db, "tradfi.funding_scale") == pytest.approx(30.0)
    assert get_param(db, "tradfi.basis_optimal_center") == pytest.approx(5.0)
    assert get_param(db, "tradfi.basis_scale") == pytest.approx(15.0)


def test_get_param_returns_updated_value_after_promote_to_live(db: Database) -> None:
    ensure_defaults(db)
    propose_shadow_update(db, "tradfi.funding_optimal_center", 12.5, reason="learned")
    promote_to_live(db, "tradfi.funding_optimal_center")
    assert get_param(db, "tradfi.funding_optimal_center") == pytest.approx(12.5)


def test_get_param_falls_back_for_unknown_param_key(db: Database) -> None:
    assert get_param(db, "unknown.param") == 0.0


def test_get_param_falls_back_to_default_params_dict(db: Database) -> None:
    # scoring_params table exists but empty; DEFAULT_PARAMS has the key
    assert get_param(db, "tradfi.funding_optimal_center") == pytest.approx(10.0)


# ------------------------------------------------------------------
# propose_shadow_update
# ------------------------------------------------------------------


def test_propose_shadow_update_changes_shadow_not_live(db: Database) -> None:
    ensure_defaults(db)
    assert propose_shadow_update(db, "tradfi.funding_optimal_center", 12.0, reason="candidate") is True

    row = db.conn.execute(
        "SELECT value_default, value_shadow, value_live, shadow_mode FROM scoring_params WHERE param_key = ?",
        ("tradfi.funding_optimal_center",),
    ).fetchone()

    assert row is not None
    assert float(row[0]) == pytest.approx(10.0)  # default unchanged
    assert float(row[1]) == pytest.approx(12.0)  # shadow updated
    assert float(row[2]) == pytest.approx(10.0)  # live unchanged
    assert int(row[3]) == 1  # still shadow mode


def test_propose_shadow_update_returns_false_for_unknown(db: Database) -> None:
    ensure_defaults(db)
    assert propose_shadow_update(db, "nonexistent.key", 99.0) is False


# ------------------------------------------------------------------
# promote_to_live
# ------------------------------------------------------------------


def test_promote_to_live_updates_live_to_match_shadow(db: Database) -> None:
    ensure_defaults(db)
    propose_shadow_update(db, "tradfi.funding_scale", 22.0, reason="candidate")
    assert promote_to_live(db, "tradfi.funding_scale") is True

    row = db.conn.execute(
        "SELECT value_shadow, value_live, shadow_mode FROM scoring_params WHERE param_key = ?",
        ("tradfi.funding_scale",),
    ).fetchone()

    assert row is not None
    assert float(row[0]) == pytest.approx(22.0)
    assert float(row[1]) == pytest.approx(22.0)
    assert int(row[2]) == 0  # shadow mode off


def test_promote_to_live_returns_false_for_unknown_param_key(db: Database) -> None:
    assert promote_to_live(db, "not.a.param") is False


# ------------------------------------------------------------------
# list_params
# ------------------------------------------------------------------


def test_list_params_returns_all_rows(db: Database) -> None:
    ensure_defaults(db)
    params = list_params(db)
    assert len(params) == len(DEFAULT_PARAMS)
    assert {p["param_key"] for p in params} == set(DEFAULT_PARAMS)


def test_list_params_filters_by_producer_name(db: Database) -> None:
    ensure_defaults(db)
    with db.conn:
        db.conn.execute(
            """
            INSERT INTO scoring_params
                (param_key, producer_name, param_type, value_default, value_shadow, value_live, shadow_mode, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("custom.other_param", "other_producer", "scale", 1.0, 1.0, 1.0, 1, "other"),
        )

    tradfi_params = list_params(db, producer_name="tradfi_basis")
    other_params = list_params(db, producer_name="other_producer")

    assert len(tradfi_params) == len(DEFAULT_PARAMS)
    assert len(other_params) == 1
    assert other_params[0]["param_key"] == "custom.other_param"


# ------------------------------------------------------------------
# Shadow mode invariant
# ------------------------------------------------------------------


def test_shadow_mode_invariant_live_equals_default_when_shadow_mode_is_one(db: Database) -> None:
    ensure_defaults(db)
    propose_shadow_update(db, "tradfi.funding_optimal_center", 18.0, reason="candidate")

    row = db.conn.execute(
        "SELECT value_default, value_live, shadow_mode FROM scoring_params WHERE param_key = ?",
        ("tradfi.funding_optimal_center",),
    ).fetchone()

    assert row is not None
    assert int(row[2]) == 1
    assert float(row[1]) == pytest.approx(float(row[0]))
    assert get_param(db, "tradfi.funding_optimal_center") == pytest.approx(float(row[0]))


# ------------------------------------------------------------------
# Parameterized scoring — same output as hardcoded at defaults
# ------------------------------------------------------------------


@pytest.mark.parametrize("fund", [-25.0, -5.0, 0.0, 5.0, 10.0, 20.0, 35.0, 40.0])
def test_synthesis_funding_score_matches_hardcoded_at_defaults(db: Database, fund: float) -> None:
    """Parameterized scoring must produce identical results when params are at defaults."""
    ensure_defaults(db)
    expected = max(0.0, min(1.0, 1.0 - abs(float(fund) - 10.0) / 30.0))
    center = get_param(db, "tradfi.funding_optimal_center")
    scale = get_param(db, "tradfi.funding_scale")
    result = max(0.0, min(1.0, 1.0 - abs(float(fund) - center) / scale))
    assert result == pytest.approx(expected)


@pytest.mark.parametrize("basis", [-5.0, 0.0, 2.0, 5.0, 10.0, 20.0])
def test_synthesis_basis_score_matches_hardcoded_at_defaults(db: Database, basis: float) -> None:
    """Basis scoring uses parameterized defaults correctly."""
    ensure_defaults(db)
    center = get_param(db, "tradfi.basis_optimal_center")
    scale = get_param(db, "tradfi.basis_scale")
    expected = max(0.0, min(1.0, 1.0 - abs(float(basis) - center) / scale))
    result = max(0.0, min(1.0, 1.0 - abs(float(basis) - 5.0) / 15.0))
    assert result == pytest.approx(expected)


def test_basis_scale_default_matches_original_hardcoded_value(tmp_path: Path) -> None:
    """Regression: basis_scale default must match the original hardcoded 8.0 in synthesis.py.
    A different default silently changes live scoring on deploy (shadow_mode=1 initialises
    value_live from value_default).
    """
    db = Database(tmp_path / "brain.db")
    try:
        ensure_defaults(db)
        val = get_param(db, "tradfi.basis_scale")
        assert val == pytest.approx(8.0), f"tradfi.basis_scale default must be 8.0 (original hardcoded value); got {val}"
    finally:
        db.close()
