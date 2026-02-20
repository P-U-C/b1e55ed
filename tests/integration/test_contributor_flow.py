from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import create_app
from engine.core.database import Database


def test_contributor_register_submit_signal_and_attribution(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    os.environ.setdefault("B1E55ED_DEV_MODE", "1")

    app = create_app()
    app.state.db = Database(tmp_path / "brain.db")

    with TestClient(app) as client:
        # register contributor
        r = client.post(
            "/api/v1/contributors/register",
            json={"node_id": "node-x", "name": "agent-x", "role": "agent", "metadata": {}},
        )
        assert r.status_code == 200, r.text
        contributor_id = r.json()["id"]

        # submit curator signal
        s = client.post(
            "/api/v1/signals/submit",
            json={
                "event_type": "signal.curator.v1",
                "node_id": "node-x",
                "source": "agent-x",
                "payload": {"symbol": "BTC", "direction": "bullish", "conviction": 7.0, "rationale": "test", "source": "agent"},
            },
        )
        assert s.status_code == 200, s.text
        event_id = s.json()["event_id"]
        assert s.json()["contributor_id"] == contributor_id

        # run brain cycle
        b = client.post("/api/v1/brain/run")
        assert b.status_code == 200, b.text

    # verify attribution persisted and accepted marked
    row = app.state.db.conn.execute(
        "SELECT contributor_id, accepted FROM contributor_signals WHERE event_id = ?",
        (event_id,),
    ).fetchone()
    assert row is not None
    assert str(row[0]) == contributor_id
    assert int(row[1]) == 1


def test_multiple_contributors_leaderboard(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    os.environ.setdefault("B1E55ED_DEV_MODE", "1")

    app = create_app()
    app.state.db = Database(tmp_path / "brain.db")

    with TestClient(app) as client:
        contributor_ids: set[str] = set()
        for i in range(2):
            node_id = f"node-{i}"
            r = client.post(
                "/api/v1/contributors/register",
                json={"node_id": node_id, "name": f"agent-{i}", "role": "agent", "metadata": {}},
            )
            assert r.status_code == 200
            contributor_ids.add(r.json()["id"])

            s = client.post(
                "/api/v1/signals/submit",
                json={
                    "event_type": "signal.curator.v1",
                    "node_id": node_id,
                    "source": f"agent-{i}",
                    "payload": {"symbol": "BTC", "direction": "bullish", "conviction": 5.0 + i, "rationale": "t", "source": "agent"},
                },
            )
            assert s.status_code == 200

        client.post("/api/v1/brain/run")

        lb = client.get("/api/v1/contributors/leaderboard?limit=10")
        assert lb.status_code == 200
        data = lb.json()
        ids = {d["contributor_id"] for d in data}
        assert contributor_ids.issubset(ids)
