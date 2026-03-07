"""Tests for the social pipeline API routes."""

from __future__ import annotations

import json

import pytest

from api.main import create_app
from engine.core.database import Database
from tests.unit._api_test_client import make_client

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017


def _seed_social_producers(db: Database) -> None:
    """Insert mock social producers into producer_health."""
    db.conn.execute(
        """
        INSERT OR IGNORE INTO producer_health (name, domain, schedule, consecutive_failures, events_produced)
        VALUES ('social-intel', 'social', '*/15 * * * *', 10, 0)
        """
    )
    db.conn.execute(
        """
        INSERT OR IGNORE INTO producer_health (name, domain, schedule, consecutive_failures, events_produced)
        VALUES ('market-sentiment', 'social', '*/15 * * * *', 3, 0)
        """
    )
    db.conn.commit()


def _seed_curator_events(db: Database) -> None:
    """Insert mock curator signal events."""
    import hashlib
    from datetime import datetime

    for i, (symbol, direction) in enumerate([("BTC", "bullish"), ("ETH", "bearish"), ("SOL", "bullish")]):
        ts = datetime(2025, 7, 1, 12, i, 0, tzinfo=UTC).isoformat()
        payload = json.dumps(
            {
                "symbol": symbol,
                "direction": direction,
                "conviction": 7 + i,
                "rationale": f"Test signal for {symbol}",
            }
        )
        event_id = f"test-curator-{i}"
        hash_val = hashlib.sha256(f"{event_id}{payload}".encode()).hexdigest()
        db.conn.execute(
            """
            INSERT OR IGNORE INTO events (id, type, ts, source, payload, hash)
            VALUES (?, 'signal.curator.v1', ?, 'zoz', ?, ?)
            """,
            (event_id, ts, payload, hash_val),
        )
    db.conn.commit()


# To test for echo chambers, first build one.
# The experimenter who constructs the bias is the only one qualified to detect it.
def _seed_social_events(db: Database) -> None:
    """Insert mock social signal events (with echo chamber flag)."""
    import hashlib
    from datetime import datetime

    for i, (symbol, score, echo) in enumerate([("BTC", 0.8, False), ("ETH", -0.3, True), ("SOL", 0.5, False)]):
        ts = datetime(2025, 7, 1, 14, i, 0, tzinfo=UTC).isoformat()
        payload = json.dumps(
            {
                "symbol": symbol,
                "score": score,
                "direction": "bullish" if score > 0 else "bearish",
                "source_count": 5 + i,
                "echo_chamber_flag": echo,
                "contrarian_flag": False,
            }
        )
        event_id = f"test-social-{i}"
        hash_val = hashlib.sha256(f"{event_id}{payload}".encode()).hexdigest()
        db.conn.execute(
            """
            INSERT OR IGNORE INTO events (id, type, ts, source, payload, hash)
            VALUES (?, 'signal.social.v1', ?, 'social-intel', ?, ?)
            """,
            (event_id, ts, payload, hash_val),
        )
    db.conn.commit()


@pytest.fixture()
def _app_and_headers(temp_dir, test_config):
    test_config = test_config.model_copy(update={"api": test_config.api.model_copy(update={"auth_token": "secret"})})
    app = create_app()
    app.state.config = test_config
    app.state.db = Database(temp_dir / "brain.db")
    headers = {"Authorization": "Bearer secret"}
    yield app, headers, app.state.db
    app.state.db.close()


# ---------------------------------------------------------------------------
# GET /social/status
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_social_status_empty_db(_app_and_headers):
    app, headers, db = _app_and_headers
    async with make_client(app) as ac:
        r = await ac.get("/api/v1/social/status", headers=headers)
        assert r.status_code == 200
        js = r.json()
        assert "pipeline_status" in js
        assert "diagnosis" in js
        assert "actions_available" in js
        assert "watchlist" in js
        assert isinstance(js["watchlist"], list)
        assert js["seeded"] is False


@pytest.mark.anyio
async def test_social_status_with_producers(_app_and_headers):
    app, headers, db = _app_and_headers
    _seed_social_producers(db)
    async with make_client(app) as ac:
        r = await ac.get("/api/v1/social/status", headers=headers)
        assert r.status_code == 200
        js = r.json()
        assert js["pipeline_status"] in ("unconfigured", "down", "degraded", "active")
        assert len(js["producers"]) == 2
        # Not seeded yet so should be unconfigured
        assert js["seeded"] is False
        assert "seed_default_watchlist" in js["actions_available"]
        assert "reset_failures" in js["actions_available"]


# ---------------------------------------------------------------------------
# POST /social/seed
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_social_seed(_app_and_headers):
    app, headers, db = _app_and_headers
    async with make_client(app) as ac:
        r = await ac.post(
            "/api/v1/social/seed",
            headers=headers,
            json={"watchlist": ["BTC", "ETH", "SOL"]},
        )
        assert r.status_code == 200
        js = r.json()
        assert js["seeded"] is True
        assert js["count"] == 3

        # Verify status now shows seeded
        r2 = await ac.get("/api/v1/social/status", headers=headers)
        assert r2.json()["seeded"] is True
        assert r2.json()["watchlist_count"] == 3


@pytest.mark.anyio
async def test_social_seed_default(_app_and_headers):
    app, headers, db = _app_and_headers
    async with make_client(app) as ac:
        r = await ac.post("/api/v1/social/seed", headers=headers, json={})
        assert r.status_code == 200
        js = r.json()
        assert js["seeded"] is True
        assert js["count"] == 5  # default: BTC, ETH, SOL, HYPE, SUI


@pytest.mark.anyio
async def test_social_seed_idempotent(_app_and_headers):
    app, headers, db = _app_and_headers
    async with make_client(app) as ac:
        r1 = await ac.post("/api/v1/social/seed", headers=headers, json={"watchlist": ["BTC"]})
        assert r1.json()["count"] == 1

        r2 = await ac.post("/api/v1/social/seed", headers=headers, json={"watchlist": ["BTC"]})
        assert r2.json()["count"] == 0  # already exists


# ---------------------------------------------------------------------------
# POST /social/reset-failures
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_social_reset_failures(_app_and_headers):
    app, headers, db = _app_and_headers
    _seed_social_producers(db)

    async with make_client(app) as ac:
        r = await ac.post("/api/v1/social/reset-failures", headers=headers, json={})
        assert r.status_code == 200
        js = r.json()
        assert js["reset"] is True
        assert js["producers_reset"] == 2

        # Verify failures actually reset
        r2 = await ac.get("/api/v1/social/status", headers=headers)
        producers = r2.json()["producers"]
        for p in producers:
            assert p["consecutive_failures"] == 0


# ---------------------------------------------------------------------------
# GET /social/curator-feed
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_social_curator_feed_empty(_app_and_headers):
    app, headers, db = _app_and_headers
    async with make_client(app) as ac:
        r = await ac.get("/api/v1/social/curator-feed", headers=headers)
        assert r.status_code == 200
        assert r.json()["items"] == []


@pytest.mark.anyio
async def test_social_curator_feed_with_data(_app_and_headers):
    app, headers, db = _app_and_headers
    _seed_curator_events(db)

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/social/curator-feed", headers=headers)
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 3
        symbols = {i["symbol"] for i in items}
        assert symbols == {"BTC", "ETH", "SOL"}
        # Check fields present
        for item in items:
            assert "direction" in item
            assert "conviction" in item
            assert "rationale" in item
            assert "source" in item
            assert "ts" in item


# ---------------------------------------------------------------------------
# GET /social/sentiment
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_social_sentiment_empty(_app_and_headers):
    app, headers, db = _app_and_headers
    async with make_client(app) as ac:
        r = await ac.get("/api/v1/social/sentiment", headers=headers)
        assert r.status_code == 200
        js = r.json()
        assert js["items"] == []
        assert js["empty_reason"] is not None


@pytest.mark.anyio
async def test_social_sentiment_with_data(_app_and_headers):
    app, headers, db = _app_and_headers
    _seed_social_events(db)

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/social/sentiment", headers=headers)
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 3


# ---------------------------------------------------------------------------
# GET /social/alerts
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_social_alerts_with_echo_chamber(_app_and_headers):
    app, headers, db = _app_and_headers
    _seed_social_events(db)

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/social/alerts", headers=headers)
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 1  # only ETH has echo_chamber_flag=True
        assert items[0]["symbol"] == "ETH"
        assert items[0]["type"] == "echo_chamber"


# ---------------------------------------------------------------------------
# GET /social/narratives
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_social_narratives_empty(_app_and_headers):
    app, headers, db = _app_and_headers
    async with make_client(app) as ac:
        r = await ac.get("/api/v1/social/narratives", headers=headers)
        assert r.status_code == 200
        js = r.json()
        assert js["items"] == []
        assert "message" in js
        assert len(js["message"]) > 0


# ---------------------------------------------------------------------------
# GET /social/sources
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_social_sources_empty(_app_and_headers):
    app, headers, db = _app_and_headers
    async with make_client(app) as ac:
        r = await ac.get("/api/v1/social/sources", headers=headers)
        assert r.status_code == 200
        assert r.json()["items"] == []


# ---------------------------------------------------------------------------
# POST /social/watchlist/add
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_add_to_watchlist(_app_and_headers):
    app, headers, db = _app_and_headers
    async with make_client(app) as ac:
        r = await ac.post(
            "/api/v1/social/watchlist/add",
            headers=headers,
            json={"symbol": "avax"},
        )
        assert r.status_code == 200
        js = r.json()
        assert js["added"] is True
        assert js["symbol"] == "AVAX"

        # Verify via watchlist endpoint
        r2 = await ac.get("/api/v1/social/watchlist", headers=headers)
        assert r2.status_code == 200
        assert r2.json()["count"] == 1


# ---------------------------------------------------------------------------
# POST /social/sources/add
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_add_source(_app_and_headers):
    app, headers, db = _app_and_headers
    async with make_client(app) as ac:
        r = await ac.post(
            "/api/v1/social/sources/add",
            headers=headers,
            json={"name": "Cobie", "type": "twitter_account", "value": "@coabornn"},
        )
        assert r.status_code == 200
        js = r.json()
        assert js["added"] is True
        assert js["id"] > 0

        # Verify via sources endpoint
        r2 = await ac.get("/api/v1/social/sources", headers=headers)
        items = r2.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Cobie"


# ---------------------------------------------------------------------------
# POST /social/run-now
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_social_run_now(_app_and_headers):
    app, headers, db = _app_and_headers
    _seed_social_producers(db)

    async with make_client(app) as ac:
        r = await ac.post("/api/v1/social/run-now", headers=headers, json={})
        assert r.status_code == 200
        js = r.json()
        assert js["triggered"] is True
        assert "message" in js


# ---------------------------------------------------------------------------
# Auth required
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_social_requires_auth(_app_and_headers):
    app, headers, db = _app_and_headers
    async with make_client(app) as ac:
        r = await ac.get("/api/v1/social/status")
        assert r.status_code == 401
