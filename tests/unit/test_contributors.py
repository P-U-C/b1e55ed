from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from engine.core.contributors import ContributorRegistry
from engine.core.database import Database
from engine.core.scoring import ContributorScoring


def test_contributor_registry_lifecycle(tmp_path: Path) -> None:
    db = Database(tmp_path / "brain.db")
    reg = ContributorRegistry(db)

    c = reg.register(node_id="node-1", name="alice", role="agent", metadata={"v": 1})
    assert c.id

    got = reg.get(c.id)
    assert got is not None
    assert got.node_id == "node-1"

    by_node = reg.get_by_node("node-1")
    assert by_node is not None
    assert by_node.id == c.id

    all_ = reg.list_all()
    assert len(all_) == 1

    updated = reg.update(c.id, name="alice2", metadata={"v": 2})
    assert updated is not None
    assert updated.name == "alice2"
    assert updated.metadata["v"] == 2

    assert reg.deregister(c.id) is True
    assert reg.get(c.id) is None


def test_duplicate_node_id_raises(tmp_path: Path) -> None:
    db = Database(tmp_path / "brain.db")
    reg = ContributorRegistry(db)

    reg.register(node_id="node-dup", name="a", role="agent", metadata={})
    with pytest.raises(ValueError):
        reg.register(node_id="node-dup", name="b", role="agent", metadata={})


def test_scoring_and_leaderboard(tmp_path: Path) -> None:
    db = Database(tmp_path / "brain.db")
    reg = ContributorRegistry(db)

    c1 = reg.register(node_id="n1", name="one", role="agent", metadata={})
    c2 = reg.register(node_id="n2", name="two", role="agent", metadata={})

    with db.conn:
        # c1: accepted+profitable
        db.conn.execute(
            """
            INSERT INTO contributor_signals (contributor_id, event_id, signal_score, accepted, profitable, created_at)
            VALUES (?, ?, ?, 1, 1, datetime('now'))
            """,
            (c1.id, "e1", 8.0),
        )
        # c2: accepted but not profitable
        db.conn.execute(
            """
            INSERT INTO contributor_signals (contributor_id, event_id, signal_score, accepted, profitable, created_at)
            VALUES (?, ?, ?, 1, 0, datetime('now'))
            """,
            (c2.id, "e2", 8.0),
        )

    scoring = ContributorScoring(db)
    s1 = scoring.compute_score(c1.id)
    s2 = scoring.compute_score(c2.id)

    assert s1.signals_submitted == 1
    assert s1.signals_accepted == 1
    assert s1.signals_profitable == 1
    assert s1.hit_rate == 1.0

    assert s2.hit_rate == 0.0

    lb = scoring.leaderboard(limit=10)
    assert lb[0].contributor_id == c1.id


def test_auto_registration_on_startup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Isolate identity file to temp HOME.
    monkeypatch.setenv("HOME", str(tmp_path))
    os.environ.setdefault("B1E55ED_DEV_MODE", "1")

    app = create_app()
    app.state.db = Database(tmp_path / "brain.db")

    with TestClient(app) as client:
        # Trigger startup
        _ = client.get("/api/v1/health")

    reg = ContributorRegistry(app.state.db)
    items = reg.list_all()
    assert any(c.role == "operator" for c in items)
