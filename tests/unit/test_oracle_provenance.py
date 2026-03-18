"""tests.unit.test_oracle_provenance

Tests for the public provenance oracle endpoint:
    GET /api/v1/oracle/producers/{producer_id}/provenance
"""

from __future__ import annotations

from datetime import datetime, timedelta

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017


import pytest

from api.main import create_app
from engine.core.database import Database
from engine.core.events import EventType
from tests.unit._api_test_client import make_client

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def _app_and_db(temp_dir, test_config):
    db = Database(temp_dir / "brain.db")
    app = create_app()
    app.state.config = test_config
    app.state.db = db
    yield app, db
    db.close()


def _seed_events_for_producer(db: Database, producer_id: str, count: int = 5) -> None:
    """Insert `count` events with source=producer_id."""
    for i in range(count):
        db.append_event(
            event_type=EventType.SIGNAL_CURATOR_V1,
            payload={
                "symbol": "BTC",
                "direction": "bullish",
                "conviction": float(i),
                "rationale": f"test signal {i}",
                "source": producer_id,
            },
            source=producer_id,
        )


def _seed_conviction_scores(db: Database, node_id: str, count: int = 3) -> None:
    """Insert conviction_scores rows for a producer (used by attribution windows)."""
    now = datetime.now(UTC)
    for i in range(count):
        ts = (now - timedelta(days=i)).isoformat()
        outcome = 1.0 if i % 2 == 0 else -0.05
        db.conn.execute(
            """
            INSERT INTO conviction_scores
            (node_id, symbol, direction, magnitude, timeframe, ts,
             commitment_hash, outcome, outcome_ts)
            VALUES (?, 'BTC', 'long', 5.0, '1h', ?, 'testhash', ?, ?)
            """,
            (node_id, ts, outcome, ts),
        )
    db.conn.commit()


async def _register_contributor(ac, node_id: str, name: str) -> dict:
    r = await ac.post(
        "/api/v1/contributors/register",
        json={"node_id": node_id, "name": name, "role": "agent", "metadata": {}},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _submit_curator_signal(ac, *, node_id: str, source: str) -> dict:
    r = await ac.post(
        "/api/v1/signals/submit",
        json={
            "event_type": "signal.curator.v1",
            "node_id": node_id,
            "source": source,
            "payload": {
                "symbol": "BTC",
                "direction": "bullish",
                "conviction": 7.0,
                "rationale": "provenance identity test",
            },
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProvenanceFound:
    @pytest.mark.anyio
    async def test_provenance_found(self, _app_and_db):
        app, db = _app_and_db
        pid = "test_producer_found"
        _seed_events_for_producer(db, pid)

        async with make_client(app) as ac:
            r = await ac.get(f"/api/v1/oracle/producers/{pid}/provenance")

        assert r.status_code == 200
        body = r.json()
        assert body["producer_id"] == pid
        assert body["has_provenance"] is True
        assert isinstance(body["chain_verified"], bool)
        assert isinstance(body["total_signals"], int)
        assert isinstance(body["operator_coverage"], int)
        assert "note" in body
        assert "attribution_windows" in body
        assert isinstance(body["attribution_windows"], dict)


class TestProvenanceNotFound:
    @pytest.mark.anyio
    async def test_provenance_not_found(self, _app_and_db):
        app, db = _app_and_db
        pid = "producer_that_does_not_exist"

        async with make_client(app) as ac:
            r = await ac.get(f"/api/v1/oracle/producers/{pid}/provenance")

        assert r.status_code == 200
        body = r.json()
        assert body["producer_id"] == pid
        assert body["has_provenance"] is False
        assert "note" in body
        assert "No provenance" in body["note"]


class TestAntiGoodhart:
    @pytest.mark.anyio
    async def test_anti_goodhart_header_present(self, _app_and_db):
        app, db = _app_and_db
        pid = "producer_header_test"
        # No events — still should return the header.

        async with make_client(app) as ac:
            r = await ac.get(f"/api/v1/oracle/producers/{pid}/provenance")

        assert "X-Attribution-Notice" in r.headers
        notice = r.headers["X-Attribution-Notice"]
        assert "informational" in notice.lower() or "Optimizing" in notice

    @pytest.mark.anyio
    async def test_anti_goodhart_header_on_found_response(self, _app_and_db):
        app, db = _app_and_db
        pid = "producer_header_found"
        _seed_events_for_producer(db, pid)

        async with make_client(app) as ac:
            r = await ac.get(f"/api/v1/oracle/producers/{pid}/provenance")

        assert "X-Attribution-Notice" in r.headers


class TestAttributionWindows:
    @pytest.mark.anyio
    async def test_attribution_windows_computed(self, _app_and_db):
        app, db = _app_and_db
        pid = "producer_with_conviction"
        _seed_events_for_producer(db, pid)
        _seed_conviction_scores(db, pid, count=5)

        async with make_client(app) as ac:
            r = await ac.get(f"/api/v1/oracle/producers/{pid}/provenance")

        assert r.status_code == 200
        body = r.json()
        # Windows are only included when there is data
        windows = body.get("attribution_windows", {})
        for win_key, win_data in windows.items():
            assert win_key in ("7d", "30d", "90d")
            assert "signals" in win_data
            assert "hit_rate" in win_data
            assert "max_drawdown_pct" in win_data
            assert isinstance(win_data["signals"], int)
            assert isinstance(win_data["hit_rate"], float)
            assert isinstance(win_data["max_drawdown_pct"], float)


class TestNoAuthRequired:
    @pytest.mark.anyio
    async def test_oracle_no_auth_required(self, _app_and_db):
        """Oracle endpoint is public — no Authorization header needed."""
        app, db = _app_and_db
        pid = "producer_public"
        _seed_events_for_producer(db, pid)

        async with make_client(app) as ac:
            # No auth header
            r = await ac.get(f"/api/v1/oracle/producers/{pid}/provenance")

        # Must not be 401 or 403
        assert r.status_code not in (401, 403)
        assert r.status_code == 200


class TestChainVerified:
    @pytest.mark.anyio
    async def test_chain_verified_flag(self, _app_and_db):
        """Events with non-null hashes → chain_verified = True."""
        app, db = _app_and_db
        pid = "producer_chain_test"
        _seed_events_for_producer(db, pid, count=3)

        async with make_client(app) as ac:
            r = await ac.get(f"/api/v1/oracle/producers/{pid}/provenance")

        assert r.status_code == 200
        body = r.json()
        assert body["has_provenance"] is True
        # Events appended via db.append_event always have hashes
        assert body["chain_verified"] is True


class TestIdentitySemantics:
    @pytest.mark.anyio
    async def test_submit_then_query_by_node_id(self, _app_and_db):
        """submit -> provenance should resolve on canonical contributor node_id."""
        app, _db = _app_and_db

        node_id = "node-prov-api-1"
        source_alias = "operator:telegram"

        async with make_client(app) as ac:
            await _register_contributor(ac, node_id=node_id, name="Agent One")
            await _submit_curator_signal(ac, node_id=node_id, source=source_alias)

            r = await ac.get(f"/api/v1/oracle/producers/{node_id}/provenance")

        assert r.status_code == 200
        body = r.json()
        assert body["has_provenance"] is True
        assert body["producer_id"] == node_id
        assert body["total_signals"] == 1
        assert body["operator_coverage"] == 1

    @pytest.mark.anyio
    async def test_query_by_source_alias_matches_node_identity(self, _app_and_db):
        """Legacy source alias and canonical node_id should return one coherent provenance record."""
        app, _db = _app_and_db

        node_id = "node-prov-api-2"
        source_alias = "agent-display-name"

        async with make_client(app) as ac:
            await _register_contributor(ac, node_id=node_id, name="Agent Two")
            await _submit_curator_signal(ac, node_id=node_id, source=source_alias)

            by_alias = await ac.get(f"/api/v1/oracle/producers/{source_alias}/provenance")
            by_node = await ac.get(f"/api/v1/oracle/producers/{node_id}/provenance")

        assert by_alias.status_code == 200
        assert by_node.status_code == 200

        alias_body = by_alias.json()
        node_body = by_node.json()

        assert alias_body["has_provenance"] is True
        assert alias_body["producer_id"] == node_id
        assert alias_body["total_signals"] == node_body["total_signals"] == 1
        assert alias_body["operator_coverage"] == node_body["operator_coverage"] == 1
