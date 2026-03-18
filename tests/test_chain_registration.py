"""Tests for karma registration gate — threshold check, status endpoint, CLI warning.

All tests use mocked DB and config — no live chain calls.
"""

from __future__ import annotations

import os

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def _env_dev():
    """Set dev-mode env vars for test app creation."""
    os.environ["B1E55ED_INSECURE_OK"] = "1"
    os.environ["B1E55ED_DEV_MODE"] = "1"
    yield
    os.environ.pop("B1E55ED_INSECURE_OK", None)
    os.environ.pop("B1E55ED_DEV_MODE", None)


@pytest.fixture()
def test_app(_env_dev):
    """Create a FastAPI test client with in-memory DB and no-auth config."""
    from fastapi.testclient import TestClient

    from api.main import create_app
    from engine.core.config import Config

    app = create_app()

    from engine.core.database import Database

    db = Database(":memory:")
    app.state.db = db

    # Use default config with empty auth_token so auth is bypassed
    cfg = Config()
    app.state.config = cfg

    with TestClient(app) as client:
        yield client, app, db


# ---------------------------------------------------------------------------
# Config: registration_threshold field
# ---------------------------------------------------------------------------


class TestKarmaConfigThreshold:
    def test_default_threshold(self):
        from engine.core.config import KarmaConfig

        cfg = KarmaConfig()
        assert cfg.registration_threshold == 10.0

    def test_custom_threshold(self):
        from engine.core.config import KarmaConfig

        cfg = KarmaConfig(registration_threshold=25.0)
        assert cfg.registration_threshold == 25.0


# ---------------------------------------------------------------------------
# API: /chain/registration-status
# ---------------------------------------------------------------------------


class TestRegistrationStatusEndpoint:
    def test_unregistered_below_threshold(self, test_app):
        """No warning when karma is below threshold."""
        client, app, db = test_app

        # No karma intents — balance is 0
        resp = client.get("/api/v1/chain/registration-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["registered"] is False
        assert data["agent_id"] == 0
        assert data["karma_balance"] == 0.0
        assert data["threshold"] == 10.0
        assert data["threshold_reached"] is False

    def test_unregistered_above_threshold(self, test_app):
        """Warning when karma exceeds threshold and not registered."""
        client, app, db = test_app

        # Insert karma intents to exceed threshold
        db.execute(
            """
            INSERT INTO karma_intents (id, trade_id, node_id, realized_pnl_usd,
                karma_percentage, karma_amount_usd, settled, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("ki-1", "t-1", "node-1", 1000.0, 0.005, 15.0, 0, "2025-01-01T00:00:00"),
        )
        db.conn.commit()

        resp = client.get("/api/v1/chain/registration-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["registered"] is False
        assert data["karma_balance"] == 15.0
        assert data["threshold_reached"] is True

    def test_already_registered(self, test_app):
        """No warning when already registered (system_agent_id != 0)."""
        client, app, db = test_app

        # Override config with system_agent_id set
        from engine.core.config import Config

        cfg = Config()
        cfg.onchain.system_agent_id = 42
        app.state.config = cfg

        resp = client.get("/api/v1/chain/registration-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["registered"] is True
        assert data["agent_id"] == 42
        assert data["threshold_reached"] is False  # 0 karma

    def test_chain_not_configured(self, test_app):
        """chain_configured=false when onchain is disabled."""
        client, app, db = test_app

        resp = client.get("/api/v1/chain/registration-status")
        data = resp.json()
        assert data["chain_configured"] is False

    def test_chain_configured(self, test_app):
        """chain_configured=true when onchain is enabled with registry address."""
        client, app, db = test_app

        from engine.core.config import Config

        cfg = Config()
        cfg.onchain.enabled = True
        cfg.onchain.identity_registry_address = "0x" + "ab" * 20
        app.state.config = cfg

        resp = client.get("/api/v1/chain/registration-status")
        data = resp.json()
        assert data["chain_configured"] is True

    def test_is_agent_when_public_base_url_set(self, test_app):
        """is_agent=true when public_base_url is configured."""
        client, app, db = test_app

        from engine.core.config import Config

        cfg = Config()
        cfg.onchain.public_base_url = "https://b1e55ed.xyz"
        app.state.config = cfg

        resp = client.get("/api/v1/chain/registration-status")
        data = resp.json()
        assert data["is_agent"] is True

    def test_is_human_when_no_public_base_url(self, test_app):
        """is_agent=false when public_base_url is empty."""
        client, app, db = test_app

        resp = client.get("/api/v1/chain/registration-status")
        data = resp.json()
        assert data["is_agent"] is False


# ---------------------------------------------------------------------------
# Integration: full flow scenario
# ---------------------------------------------------------------------------


class TestRegistrationGateFlow:
    def test_full_flow_below_then_above_threshold(self, test_app):
        """Karma starts below threshold, then crosses it."""
        client, app, db = test_app

        from engine.core.config import Config

        cfg = Config()
        cfg.onchain.enabled = True
        cfg.onchain.identity_registry_address = "0x" + "ab" * 20
        cfg.karma.registration_threshold = 5.0
        app.state.config = cfg

        # Step 1: Below threshold
        resp = client.get("/api/v1/chain/registration-status")
        data = resp.json()
        assert data["threshold_reached"] is False
        assert data["chain_configured"] is True

        # Step 2: Add karma to cross threshold
        db.execute(
            """
            INSERT INTO karma_intents (id, trade_id, node_id, realized_pnl_usd,
                karma_percentage, karma_amount_usd, settled, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("ki-flow-1", "t-flow-1", "node-1", 2000.0, 0.005, 7.5, 0, "2025-06-01T00:00:00"),
        )
        db.conn.commit()

        # Step 3: Now above threshold
        resp = client.get("/api/v1/chain/registration-status")
        data = resp.json()
        assert data["threshold_reached"] is True
        assert data["karma_balance"] == 7.5
        assert data["registered"] is False

    def test_registered_node_no_warning(self, test_app):
        """After registration, threshold_reached doesn't matter — registered=true."""
        client, app, db = test_app

        from engine.core.config import Config

        cfg = Config()
        cfg.onchain.enabled = True
        cfg.onchain.system_agent_id = 99
        cfg.onchain.identity_registry_address = "0x" + "ab" * 20
        app.state.config = cfg

        # Add karma above threshold
        db.execute(
            """
            INSERT INTO karma_intents (id, trade_id, node_id, realized_pnl_usd,
                karma_percentage, karma_amount_usd, settled, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("ki-reg-1", "t-reg-1", "node-1", 5000.0, 0.005, 25.0, 0, "2025-06-01T00:00:00"),
        )
        db.conn.commit()

        resp = client.get("/api/v1/chain/registration-status")
        data = resp.json()
        assert data["registered"] is True
        assert data["agent_id"] == 99
        assert data["karma_balance"] == 25.0
        # Even though threshold_reached is true, registered overrides
        assert data["threshold_reached"] is True
