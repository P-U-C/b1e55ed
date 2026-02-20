from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from engine.core.contributors import ContributorRegistry
from engine.core.database import Database
from engine.core.scoring import ContributorScoring


def _insert_signal(db: Database, *, contributor_id: str, event_id: str, accepted: int, profitable: int | None, score: float, created_at: datetime) -> None:
    with db.conn:
        db.conn.execute(
            """
            INSERT INTO contributor_signals (contributor_id, event_id, accepted, profitable, signal_score, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (contributor_id, event_id, accepted, profitable, score, created_at.isoformat()),
        )


def test_hit_rate_calculation(tmp_path: Path) -> None:
    db = Database(tmp_path / "brain.db")
    reg = ContributorRegistry(db)
    c = reg.register(node_id="n", name="x", role="agent", metadata={})

    now = datetime.now(tz=UTC)
    _insert_signal(db, contributor_id=c.id, event_id="e1", accepted=1, profitable=1, score=5.0, created_at=now)
    _insert_signal(db, contributor_id=c.id, event_id="e2", accepted=1, profitable=0, score=5.0, created_at=now)

    s = ContributorScoring(db).compute_score(c.id)
    assert s.signals_accepted == 2
    assert s.signals_profitable == 1
    assert abs(s.hit_rate - 0.5) < 1e-9


def test_streak_counting(tmp_path: Path) -> None:
    db = Database(tmp_path / "brain.db")
    reg = ContributorRegistry(db)
    c = reg.register(node_id="n", name="x", role="agent", metadata={})

    now = datetime.now(tz=UTC)
    _insert_signal(db, contributor_id=c.id, event_id="e1", accepted=0, profitable=None, score=1.0, created_at=now)
    _insert_signal(db, contributor_id=c.id, event_id="e2", accepted=0, profitable=None, score=1.0, created_at=now - timedelta(days=1))
    _insert_signal(db, contributor_id=c.id, event_id="e3", accepted=0, profitable=None, score=1.0, created_at=now - timedelta(days=2))

    s = ContributorScoring(db).compute_score(c.id)
    assert s.streak == 3


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
