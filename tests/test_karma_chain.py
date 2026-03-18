"""Tests for ERC-8004 E2 — KarmaChainWriter, karma_chain_queue, outcome endpoint.

At least 8 tests covering:
- KarmaChainWriter with chain_client=None → no-ops
- queue_karma_event + flush with mocked chain_client → calls post_karma_feedback
- DB table created on init
- outcome JSON format is valid JSON
- Outcome API endpoint
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# DB table tests
# ---------------------------------------------------------------------------


class TestKarmaChainQueueTable:
    def test_table_created_on_init(self):
        """karma_chain_queue table should exist after Database init."""
        from engine.core.database import Database

        db = Database(":memory:")
        tables = [str(r[0]) for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='karma_chain_queue'").fetchall()]
        assert "karma_chain_queue" in tables

    def test_table_has_correct_columns(self):
        from engine.core.database import Database

        db = Database(":memory:")
        cols = [str(r[1]) for r in db.conn.execute("PRAGMA table_info(karma_chain_queue)").fetchall()]
        expected = ["id", "agent_id", "karma_delta", "forecast_id", "producer_node_id", "outcome_json", "status", "tx_hash", "created_at", "submitted_at"]
        for col in expected:
            assert col in cols, f"Missing column: {col}"

    def test_default_status_is_pending(self):
        from engine.core.database import Database

        db = Database(":memory:")
        db.execute(
            "INSERT INTO karma_chain_queue (agent_id, karma_delta, forecast_id, producer_node_id) VALUES (?, ?, ?, ?)",
            (1, 0.5, "fc-001", "node-a"),
        )
        db.conn.commit()
        row = db.execute("SELECT status FROM karma_chain_queue WHERE forecast_id = ?", ("fc-001",)).fetchone()
        assert row["status"] == "pending"


# ---------------------------------------------------------------------------
# KarmaChainWriter no-op tests (chain_client=None)
# ---------------------------------------------------------------------------


class TestKarmaChainWriterNoOp:
    def test_queue_noop_when_no_chain_client(self):
        """queue_karma_event should be a no-op when chain_client is None."""
        from engine.brain.karma_chain import KarmaChainWriter
        from engine.core.database import Database

        db = Database(":memory:")
        writer = KarmaChainWriter(chain_client=None, db=db)
        # Should not raise, and should not insert into DB
        writer.queue_karma_event(agent_id=1, karma_delta=0.5, forecast_id="fc-noop", producer_node_id="node-x")
        row = db.execute("SELECT COUNT(*) as cnt FROM karma_chain_queue").fetchone()
        assert row["cnt"] == 0

    def test_flush_noop_when_no_chain_client(self):
        """flush should return empty list when chain_client is None."""
        from engine.brain.karma_chain import KarmaChainWriter
        from engine.core.database import Database

        db = Database(":memory:")
        writer = KarmaChainWriter(chain_client=None, db=db)
        result = writer.flush()
        assert result == []


# ---------------------------------------------------------------------------
# KarmaChainWriter with mocked chain_client
# ---------------------------------------------------------------------------


class TestKarmaChainWriterWithMock:
    def test_queue_and_flush_calls_post_karma(self):
        """queue + flush should call post_karma_feedback on the chain client."""
        from engine.brain.karma_chain import KarmaChainWriter
        from engine.core.database import Database

        db = Database(":memory:")
        mock_chain = MagicMock()
        mock_chain.post_karma_feedback.return_value = "0xdeadbeef"

        writer = KarmaChainWriter(chain_client=mock_chain, db=db)
        writer.queue_karma_event(agent_id=42, karma_delta=1.5, forecast_id="fc-mock-001", producer_node_id="node-test")

        tx_hashes = writer.flush()

        assert tx_hashes == ["0xdeadbeef"]
        mock_chain.post_karma_feedback.assert_called_once()
        call_kwargs = mock_chain.post_karma_feedback.call_args
        assert call_kwargs.kwargs["agent_id"] == 42
        assert call_kwargs.kwargs["karma_delta"] == 1.5
        assert call_kwargs.kwargs["tag"] == "karma"
        assert "fc-mock-001" in call_kwargs.kwargs["file_uri"]
        assert len(call_kwargs.kwargs["file_hash"]) == 32

    def test_flush_marks_submitted_in_db(self):
        from engine.brain.karma_chain import KarmaChainWriter
        from engine.core.database import Database

        db = Database(":memory:")
        mock_chain = MagicMock()
        mock_chain.post_karma_feedback.return_value = "0xcafebabe"

        writer = KarmaChainWriter(chain_client=mock_chain, db=db)
        writer.queue_karma_event(agent_id=10, karma_delta=-0.5, forecast_id="fc-sub-001", producer_node_id="node-b")
        writer.flush()

        row = db.execute("SELECT status, tx_hash FROM karma_chain_queue WHERE forecast_id = ?", ("fc-sub-001",)).fetchone()
        assert row["status"] == "submitted"
        assert row["tx_hash"] == "0xcafebabe"

    def test_flush_marks_failed_on_none_return(self):
        from engine.brain.karma_chain import KarmaChainWriter
        from engine.core.database import Database

        db = Database(":memory:")
        mock_chain = MagicMock()
        mock_chain.post_karma_feedback.return_value = None  # chain call failed

        writer = KarmaChainWriter(chain_client=mock_chain, db=db)
        writer.queue_karma_event(agent_id=10, karma_delta=0.3, forecast_id="fc-fail-001", producer_node_id="node-c")
        tx_hashes = writer.flush()

        assert tx_hashes == []
        row = db.execute("SELECT status FROM karma_chain_queue WHERE forecast_id = ?", ("fc-fail-001",)).fetchone()
        assert row["status"] == "failed"

    def test_outcome_json_is_valid(self):
        """The outcome JSON built by _build_outcome_json should be valid JSON."""
        from engine.brain.karma_chain import KarmaChainWriter
        from engine.core.database import Database

        db = Database(":memory:")
        writer = KarmaChainWriter(chain_client=None, db=db)
        outcome = writer._build_outcome_json(
            {
                "agent_id": 5,
                "karma_delta": 1.0,
                "forecast_id": "fc-json-test",
                "producer_node_id": "node-j",
            }
        )
        parsed = json.loads(outcome)
        assert parsed["version"] == "1.0"
        assert parsed["type"] == "karma_outcome"
        assert parsed["agent_id"] == 5
        assert parsed["forecast_id"] == "fc-json-test"
        assert "timestamp" in parsed

    def test_batch_size_limits_flush(self):
        """flush should respect batch_size."""
        from engine.brain.karma_chain import KarmaChainWriter
        from engine.core.database import Database

        db = Database(":memory:")
        mock_chain = MagicMock()
        mock_chain.post_karma_feedback.return_value = "0xbatch"

        writer = KarmaChainWriter(chain_client=mock_chain, db=db, batch_size=2)
        for i in range(5):
            writer.queue_karma_event(agent_id=i, karma_delta=0.1, forecast_id=f"fc-batch-{i}", producer_node_id="node-batch")

        tx_hashes = writer.flush()
        # batch_size=2 so only 2 should be submitted
        assert len(tx_hashes) == 2
        assert mock_chain.post_karma_feedback.call_count == 2


# ---------------------------------------------------------------------------
# Outcome API endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def outcome_app():
    """Create a FastAPI test client with seeded outcome data."""
    os.environ["B1E55ED_INSECURE_OK"] = "1"
    os.environ["B1E55ED_DEV_MODE"] = "1"

    from fastapi.testclient import TestClient

    from api.main import create_app
    from engine.core.database import Database
    from engine.core.events import EventType

    app = create_app()
    db = Database(":memory:")
    app.state.db = db

    # Seed: create a forecast event and resolve it
    forecast_event = db.append_event(
        event_type=EventType.FORECAST_V1,
        payload={
            "asset": "BTC",
            "action": "long",
            "confidence": 0.8,
            "horizon": "1h",
        },
        source="test-producer@node-1",
    )

    outcome_event = db.append_event(
        event_type=EventType.FORECAST_OUTCOME_V1,
        payload={
            "forecast_event_id": forecast_event.id,
            "producer_id": "test-producer",
            "asset": "BTC",
            "horizon": "1h",
            "forecast_action": "long",
            "forecast_confidence": 0.8,
            "forecast_price": 100000.0,
            "actual_price": 101000.0,
            "return_actual_pct": 1.0,
            "direction_correct": True,
            "brier_score": 0.04,
            "regime_at_forecast": "trending",
            "resolved_at": 1700000000.0,
        },
        source="brain.outcome_resolver",
    )

    db.execute(
        "INSERT INTO forecast_resolution_state (forecast_event_id, resolved_at, outcome_event_id) VALUES (?, ?, ?)",
        (forecast_event.id, 1700000000.0, outcome_event.id),
    )
    db.conn.commit()

    # Store forecast_id for test access
    app.state.test_forecast_id = forecast_event.id
    app.state.test_outcome_id = outcome_event.id

    with TestClient(app) as client:
        yield client, app


class TestOutcomeEndpoint:
    def test_get_outcome_success(self, outcome_app):
        client, app = outcome_app
        forecast_id = app.state.test_forecast_id
        resp = client.get(f"/api/v1/outcomes/{forecast_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["forecast_id"] == forecast_id
        assert data["outcome"]["direction_correct"] is True
        assert data["outcome"]["asset"] == "BTC"

    def test_get_outcome_not_found(self, outcome_app):
        client, _ = outcome_app
        resp = client.get("/api/v1/outcomes/nonexistent-forecast-id")
        assert resp.status_code == 404

    def test_outcome_has_chain_field(self, outcome_app):
        client, app = outcome_app
        forecast_id = app.state.test_forecast_id
        resp = client.get(f"/api/v1/outcomes/{forecast_id}")
        data = resp.json()
        # chain field should be None since no karma_chain_queue entry exists
        assert "chain" in data
