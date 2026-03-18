"""Unit tests for the SPI gateway endpoints (Phase 2A).

Covers:
- Signal submission (201, 409 duplicate, 403 unknown key)
- Signal listing (producer isolation)
- Karma retrieval
- Producer registration (key format, hashed storage)
- Producer activation (lifecycle_state change)
"""

from __future__ import annotations

import hashlib

import pytest

from api.main import create_app
from engine.core.database import Database
from tests.unit._api_test_client import make_client

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register_producer(db: Database, producer_id: str = "testprod", ingress_mode: str = "native") -> str:
    """Insert a producer directly into the DB and return the plaintext key."""
    import secrets
    from datetime import UTC, datetime

    from api.routes.spi import _ensure_key_column
    from engine.spi.admission import _ensure_tables

    _ensure_tables(db)
    _ensure_key_column(db)

    raw_key = "spi_key_" + secrets.token_hex(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    now = datetime.now(tz=UTC).isoformat()
    db.execute(
        """
        INSERT INTO spi_producers (
            producer_id, producer_name, lifecycle_state, ingress_mode,
            api_key_hash, registered_at, created_at, updated_at
        ) VALUES (?, ?, 'active', ?, ?, ?, ?, ?)
        """,
        (producer_id, f"{producer_id} Name", ingress_mode, key_hash, now, now, now),
    )
    return raw_key


def _make_app(temp_dir, test_config):
    test_config = test_config.model_copy(update={"api": test_config.api.model_copy(update={"auth_token": "secret"})})
    db = Database(temp_dir / "brain.db")
    app = create_app()
    app.state.config = test_config
    app.state.db = db
    return app, db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_submit_signal_201(temp_dir, test_config):
    """POST /spi/signals → 201 with signal_id; record present in DB."""
    app, db = _make_app(temp_dir, test_config)
    key = _register_producer(db)

    async with make_client(app) as ac:
        r = await ac.post(
            "/api/v1/spi/signals",
            json={
                "symbol": "BTC-USD",
                "direction": "bullish",
                "confidence": 0.82,
                "horizon_hours": 168,
            },
            headers={"X-Producer-Key": key},
        )
        assert r.status_code == 201, r.text
        data = r.json()
        assert "signal_id" in data
        assert data["status"] == "accepted"
        assert "attribution_window_end" in data

        # Verify in DB
        row = db.fetchone(
            "SELECT signal_id FROM spi_signals WHERE signal_id = ?",
            (data["signal_id"],),
        )
        assert row is not None

    db.close()


@pytest.mark.anyio
async def test_submit_signal_duplicate_409(temp_dir, test_config):
    """Submitting the same client_signal_id twice → 409."""
    app, db = _make_app(temp_dir, test_config)
    key = _register_producer(db)

    payload = {
        "symbol": "ETH-USD",
        "direction": "bearish",
        "confidence": 0.70,
        "horizon_hours": 48,
        "client_signal_id": "idempotency-key-abc",
    }

    async with make_client(app) as ac:
        r1 = await ac.post("/api/v1/spi/signals", json=payload, headers={"X-Producer-Key": key})
        assert r1.status_code == 201

        r2 = await ac.post("/api/v1/spi/signals", json=payload, headers={"X-Producer-Key": key})
        assert r2.status_code == 409
        assert r2.json()["error"]["code"] == "spi.duplicate_signal"

    db.close()


@pytest.mark.anyio
async def test_submit_signal_unknown_key_403(temp_dir, test_config):
    """Unknown X-Producer-Key → 403."""
    app, db = _make_app(temp_dir, test_config)
    # Ensure tables exist but register NO producers
    from api.routes.spi import _ensure_key_column
    from engine.spi.admission import _ensure_tables

    _ensure_tables(db)
    _ensure_key_column(db)

    async with make_client(app) as ac:
        r = await ac.post(
            "/api/v1/spi/signals",
            json={"symbol": "BTC-USD", "direction": "bullish", "confidence": 0.8, "horizon_hours": 24},
            headers={"X-Producer-Key": "spi_key_notareal"},
        )
        assert r.status_code == 403
        assert "unknown_key" in r.json()["error"]["code"]

    db.close()


@pytest.mark.anyio
async def test_list_signals_producer_isolation(temp_dir, test_config):
    """GET /spi/signals returns only the authenticated producer's signals."""
    app, db = _make_app(temp_dir, test_config)
    key_a = _register_producer(db, producer_id="prodA")
    key_b = _register_producer(db, producer_id="prodB")

    async with make_client(app) as ac:
        # Producer A submits 2 signals
        for _i in range(2):
            await ac.post(
                "/api/v1/spi/signals",
                json={"symbol": "BTC-USD", "direction": "bullish", "confidence": 0.7, "horizon_hours": 24},
                headers={"X-Producer-Key": key_a},
            )
        # Producer B submits 1 signal
        await ac.post(
            "/api/v1/spi/signals",
            json={"symbol": "ETH-USD", "direction": "bearish", "confidence": 0.6, "horizon_hours": 12},
            headers={"X-Producer-Key": key_b},
        )

        # Producer A lists → only sees its own 2 signals
        r = await ac.get("/api/v1/spi/signals", headers={"X-Producer-Key": key_a})
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 2
        assert all(s["symbol"] == "BTC-USD" for s in data["signals"])

        # Producer B lists → only sees its own 1 signal
        r2 = await ac.get("/api/v1/spi/signals", headers={"X-Producer-Key": key_b})
        assert r2.status_code == 200
        data2 = r2.json()
        assert data2["total"] == 1
        assert data2["signals"][0]["symbol"] == "ETH-USD"

    db.close()


@pytest.mark.anyio
async def test_get_karma_correct_producer(temp_dir, test_config):
    """GET /spi/producers/{id}/karma returns correct karma for that producer."""
    app, db = _make_app(temp_dir, test_config)
    key = _register_producer(db, producer_id="karmaprod")

    from datetime import UTC, datetime

    from engine.spi.admission import _ensure_tables

    _ensure_tables(db)

    # Insert a karma row
    now = datetime.now(tz=UTC).isoformat()
    db.execute(
        """
        INSERT INTO spi_karma (producer_id, epoch, epoch_brier, epoch_karma, running_karma, resolved_count, updated_at)
        VALUES (?, 1, 0.15, 0.80, 0.73, 5, ?)
        """,
        ("karmaprod", now),
    )

    async with make_client(app) as ac:
        r = await ac.get("/api/v1/spi/producers/karmaprod/karma", headers={"X-Producer-Key": key})
        assert r.status_code == 200
        data = r.json()
        assert data["producer_id"] == "karmaprod"
        assert abs(data["running_karma"] - 0.73) < 0.001
        assert data["epoch"] == 1
        assert data["resolved_count"] == 5

    db.close()


@pytest.mark.anyio
async def test_register_producer_generates_key(temp_dir, test_config):
    """POST /spi/producers creates producer with key stored hashed; returns plaintext key once."""
    app, db = _make_app(temp_dir, test_config)

    async with make_client(app) as ac:
        r = await ac.post(
            "/api/v1/spi/producers",
            json={"producer_id": "newprod", "producer_name": "New Prod", "ingress_mode": "native"},
        )
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["producer_id"] == "newprod"
        api_key = data["api_key"]
        assert api_key.startswith("spi_key_")

        # Verify hash stored in DB (not plaintext)
        row = db.fetchone("SELECT api_key_hash FROM spi_producers WHERE producer_id = ?", ("newprod",))
        assert row is not None
        stored_hash = row[0]
        expected_hash = hashlib.sha256(api_key.encode()).hexdigest()
        assert stored_hash == expected_hash
        assert stored_hash != api_key  # plaintext NOT stored

    db.close()


@pytest.mark.anyio
async def test_activate_producer_changes_lifecycle(temp_dir, test_config):
    """POST /spi/producers/{id}/activate transitions lifecycle_state to 'active'."""
    app, db = _make_app(temp_dir, test_config)

    from datetime import UTC, datetime

    from api.routes.spi import _ensure_key_column
    from engine.spi.admission import _ensure_tables

    _ensure_tables(db)
    _ensure_key_column(db)

    # Insert producer in shadow state (shadow→active is valid; onboarding→active is not)
    now = datetime.now(tz=UTC).isoformat()
    db.execute(
        """
        INSERT INTO spi_producers (producer_id, producer_name, lifecycle_state, ingress_mode,
            api_key_hash, registered_at, created_at, updated_at)
        VALUES (?, ?, 'shadow', 'native', ?, ?, ?, ?)
        """,
        ("onboard_prod", "Onboarding Prod", "fakehash", now, now, now),
    )

    async with make_client(app) as ac:
        r = await ac.post("/api/v1/spi/producers/onboard_prod/activate")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["lifecycle_state"] == "active"
        assert data["producer_id"] == "onboard_prod"

    # Verify in DB
    row = db.fetchone("SELECT lifecycle_state FROM spi_producers WHERE producer_id = ?", ("onboard_prod",))
    assert row[0] == "active"

    db.close()


@pytest.mark.anyio
async def test_api_key_format_validation(temp_dir, test_config):
    """Registered API keys always start with 'spi_key_' prefix."""
    app, db = _make_app(temp_dir, test_config)

    async with make_client(app) as ac:
        r = await ac.post(
            "/api/v1/spi/producers",
            json={"producer_id": "prefix_test", "producer_name": "Prefix Test"},
        )
        assert r.status_code == 201
        key = r.json()["api_key"]
        assert key.startswith("spi_key_"), f"Key does not have spi_key_ prefix: {key!r}"
        # Ensure it's long enough to be meaningful (prefix + 64 hex chars)
        assert len(key) >= len("spi_key_") + 64

    db.close()
