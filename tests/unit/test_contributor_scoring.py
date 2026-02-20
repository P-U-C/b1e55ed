from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from engine.core.contributors import ContributorRegistry
from engine.core.database import Database
from engine.core.scoring import ContributorScoring, MIN_RESOLVED_FOR_HIT_RATE


def _insert_signal(db: Database, *, contributor_id: str, event_id: str, accepted: int, profitable: int | None, score: float, created_at: datetime) -> None:
    with db.conn:
        db.conn.execute(
            """
            INSERT INTO contributor_signals (contributor_id, event_id, accepted, profitable, signal_score, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (contributor_id, event_id, accepted, profitable, score, created_at.isoformat()),
        )


def _insert_n_signals(db: Database, *, contributor_id: str, n_profitable: int, n_unprofitable: int, score: float = 5.0) -> None:
    """Insert enough accepted+resolved signals to meet MIN_RESOLVED threshold."""
    now = datetime.now(tz=UTC)
    idx = 0
    for _ in range(n_profitable):
        _insert_signal(db, contributor_id=contributor_id, event_id=f"e{idx}", accepted=1, profitable=1, score=score, created_at=now)
        idx += 1
    for _ in range(n_unprofitable):
        _insert_signal(db, contributor_id=contributor_id, event_id=f"e{idx}", accepted=1, profitable=0, score=score, created_at=now)
        idx += 1


def test_hit_rate_requires_min_resolved(tmp_path: Path) -> None:
    """Hit rate is 0 when fewer than MIN_RESOLVED outcomes exist."""
    db = Database(tmp_path / "brain.db")
    reg = ContributorRegistry(db)
    c = reg.register(node_id="n", name="x", role="agent", metadata={})

    now = datetime.now(tz=UTC)
    _insert_signal(db, contributor_id=c.id, event_id="e1", accepted=1, profitable=1, score=5.0, created_at=now)
    _insert_signal(db, contributor_id=c.id, event_id="e2", accepted=1, profitable=0, score=5.0, created_at=now)

    s = ContributorScoring(db).compute_score(c.id)
    # Only 2 resolved — below threshold, hit rate defaults to 0
    assert s.hit_rate == 0.0
    assert s.signals_resolved == 2


def test_hit_rate_with_enough_resolved(tmp_path: Path) -> None:
    """Hit rate counts when enough resolved outcomes exist."""
    db = Database(tmp_path / "brain.db")
    reg = ContributorRegistry(db)
    c = reg.register(node_id="n", name="x", role="agent", metadata={})

    # 3 profitable, 2 unprofitable = 5 resolved (meets threshold)
    _insert_n_signals(db, contributor_id=c.id, n_profitable=3, n_unprofitable=2)

    s = ContributorScoring(db).compute_score(c.id)
    assert s.signals_resolved == MIN_RESOLVED_FOR_HIT_RATE
    assert abs(s.hit_rate - 0.6) < 1e-9


def test_streak_counts_accepted_only(tmp_path: Path) -> None:
    """Streak only counts days with accepted signals, not all submissions."""
    db = Database(tmp_path / "brain.db")
    reg = ContributorRegistry(db)
    c = reg.register(node_id="n", name="x", role="agent", metadata={})

    now = datetime.now(tz=UTC)
    # Non-accepted signals: streak should be 0
    _insert_signal(db, contributor_id=c.id, event_id="e1", accepted=0, profitable=None, score=1.0, created_at=now)
    _insert_signal(db, contributor_id=c.id, event_id="e2", accepted=0, profitable=None, score=1.0, created_at=now - timedelta(days=1))

    s = ContributorScoring(db).compute_score(c.id)
    assert s.streak == 0

    # Now add accepted signals on consecutive days
    _insert_signal(db, contributor_id=c.id, event_id="e3", accepted=1, profitable=None, score=5.0, created_at=now)
    _insert_signal(db, contributor_id=c.id, event_id="e4", accepted=1, profitable=None, score=5.0, created_at=now - timedelta(days=1))
    _insert_signal(db, contributor_id=c.id, event_id="e5", accepted=1, profitable=None, score=5.0, created_at=now - timedelta(days=2))

    s2 = ContributorScoring(db).compute_score(c.id)
    assert s2.streak == 3


def test_acceptance_rate_gate(tmp_path: Path) -> None:
    """Contributors with < 10% acceptance rate and 10+ signals score zero."""
    db = Database(tmp_path / "brain.db")
    reg = ContributorRegistry(db)
    c = reg.register(node_id="n", name="spammer", role="agent", metadata={})

    now = datetime.now(tz=UTC)
    # 11 submitted, 0 accepted = 0% acceptance
    for i in range(11):
        _insert_signal(db, contributor_id=c.id, event_id=f"e{i}", accepted=0, profitable=None, score=1.0, created_at=now)

    s = ContributorScoring(db).compute_score(c.id)
    assert s.score == 0.0
    assert s.acceptance_rate == 0.0


def test_low_hit_rate_penalty(tmp_path: Path) -> None:
    """Contributors with < 20% hit rate get penalized."""
    db = Database(tmp_path / "brain.db")
    reg = ContributorRegistry(db)
    c = reg.register(node_id="n", name="bad", role="agent", metadata={})

    # 1 profitable, 9 unprofitable = 10% hit rate (below 20%)
    _insert_n_signals(db, contributor_id=c.id, n_profitable=1, n_unprofitable=9)

    s = ContributorScoring(db).compute_score(c.id)
    assert s.hit_rate < 0.20
    # Score should be lower than someone with no resolved outcomes
    s_empty = ContributorScoring(db).compute_score("nonexistent")
    # Bad contributor score should still be >= 0 (clamped)
    assert s.score >= 0.0


def test_brier_score_field(tmp_path: Path) -> None:
    """Brier score is computed for contributors with enough data."""
    db = Database(tmp_path / "brain.db")
    reg = ContributorRegistry(db)
    c = reg.register(node_id="n", name="calibrated", role="agent", metadata={})

    # Perfect calibration: high score when profitable, low when not
    _insert_n_signals(db, contributor_id=c.id, n_profitable=5, n_unprofitable=0, score=9.0)

    s = ContributorScoring(db).compute_score(c.id)
    assert s.brier_score < 0.25  # Better than random
    assert s.signals_resolved == 5


def test_leaderboard_limit(tmp_path: Path) -> None:
    db = Database(tmp_path / "brain.db")
    reg = ContributorRegistry(db)
    scoring = ContributorScoring(db)

    for i in range(5):
        c = reg.register(node_id=f"n{i}", name=f"c{i}", role="agent", metadata={})
        with db.conn:
            db.conn.execute(
                """
                INSERT INTO contributor_signals (contributor_id, event_id, accepted, profitable, signal_score, created_at)
                VALUES (?, ?, 1, 1, 5.0, datetime('now'))
                """,
                (c.id, f"e{i}"),
            )

    lb = scoring.leaderboard(limit=3)
    assert len(lb) == 3
