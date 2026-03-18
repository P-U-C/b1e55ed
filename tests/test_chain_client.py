"""Tests for ERC-8004 chain client, manifest endpoint, and well-known route.

No live chain calls — all tests exercise the fail-open / no-op paths.
"""

from __future__ import annotations

import json
import os

import pytest

# ---------------------------------------------------------------------------
# ChainClient unit tests (no web3 / no RPC required)
# ---------------------------------------------------------------------------


class TestChainClientNoOp:
    """When identity_registry_address is None, every method silently returns None."""

    def test_register_producer_returns_none_when_unconfigured(self):
        from engine.oracle.chain import ChainClient

        client = ChainClient(rpc_url="", private_key="", identity_registry_address=None)
        assert client.register_producer("https://example.com/manifest.json") is None

    def test_post_karma_feedback_returns_none_when_unconfigured(self):
        from engine.oracle.chain import ChainClient

        client = ChainClient(rpc_url="", private_key="", identity_registry_address=None)
        assert client.post_karma_feedback(agent_id=1, karma_delta=0.5, tag="test") is None

    def test_post_validation_returns_none_when_unconfigured(self):
        from engine.oracle.chain import ChainClient

        client = ChainClient(rpc_url="", private_key="", identity_registry_address=None)
        assert client.post_validation(agent_id=1, verdict="pass") is None

    def test_enabled_false_when_no_rpc(self):
        from engine.oracle.chain import ChainClient

        client = ChainClient(rpc_url="", private_key="")
        assert client.enabled is False

    def test_enabled_false_when_no_private_key(self):
        from engine.oracle.chain import ChainClient

        client = ChainClient(rpc_url="https://rpc.example.com", private_key="")
        assert client.enabled is False

    def test_register_returns_none_with_bad_rpc(self):
        """Even with a bogus RPC, init should not raise (fail-open)."""
        from engine.oracle.chain import ChainClient

        client = ChainClient(
            rpc_url="https://nonexistent-rpc.invalid",
            private_key="0x" + "ab" * 32,
            identity_registry_address="0x" + "00" * 20,
        )
        # register_producer should fail-open (no real RPC)
        result = client.register_producer("https://example.com/manifest.json")
        assert result is None

    def test_post_karma_with_file_hash(self):
        from engine.oracle.chain import ChainClient

        client = ChainClient(rpc_url="", private_key="")
        result = client.post_karma_feedback(
            agent_id=42,
            karma_delta=-1.5,
            tag="forecast",
            file_uri="ipfs://Qm...",
            file_hash=b"\x01" * 16,
        )
        assert result is None

    def test_post_validation_with_result_hash(self):
        from engine.oracle.chain import ChainClient

        client = ChainClient(rpc_url="", private_key="")
        result = client.post_validation(
            agent_id=42,
            verdict="block",
            result_uri="https://review.example.com/123",
            result_hash=b"\xff" * 32,
        )
        assert result is None


# ---------------------------------------------------------------------------
# OnChainConfig tests
# ---------------------------------------------------------------------------


class TestOnChainConfig:
    def test_default_values(self):
        from engine.core.config import OnChainConfig

        cfg = OnChainConfig()
        assert cfg.enabled is False
        assert cfg.rpc_url == ""
        assert cfg.private_key.get_secret_value() == ""
        assert cfg.network == "base-sepolia"
        assert cfg.identity_registry_address == ""
        assert cfg.reputation_registry_address == ""
        assert cfg.validation_registry_address == ""

    def test_custom_values(self):
        from engine.core.config import OnChainConfig

        cfg = OnChainConfig(
            enabled=True,
            rpc_url="https://rpc.example.com",
            private_key="0xdeadbeef",
            network="ethereum",
            identity_registry_address="0x1234",
        )
        assert cfg.enabled is True
        assert cfg.network == "ethereum"


# ---------------------------------------------------------------------------
# API endpoint tests (manifest + well-known)
# ---------------------------------------------------------------------------


@pytest.fixture()
def test_app():
    """Create a FastAPI test client with an in-memory database."""
    os.environ["B1E55ED_INSECURE_OK"] = "1"
    os.environ["B1E55ED_DEV_MODE"] = "1"

    from fastapi.testclient import TestClient

    from api.main import create_app

    app = create_app()

    # Set up in-memory DB with schema
    from engine.core.database import Database

    db = Database(":memory:")
    app.state.db = db

    # Insert a test contributor with agent_id
    db.execute(
        """
        INSERT INTO contributors (id, node_id, name, role, metadata, registered_at, updated_at, agent_id, chain_tx_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "test-id-001",
            "node-abc123",
            "btc-technical-analysis",
            "agent",
            json.dumps({"version": "1.0"}),
            "2025-01-01T00:00:00",
            "2025-01-01T00:00:00",
            42,
            "0xdeadbeef",
        ),
    )
    db.conn.commit()

    with TestClient(app) as client:
        yield client


class TestManifestEndpoint:
    def test_get_manifest_success(self, test_app):
        resp = test_app.get("/api/v1/agents/node-abc123/manifest")
        assert resp.status_code == 200
        data = resp.json()
        assert "registration" in data["type"]  # accept both EIP URL and internal spec URL
        assert data["name"] == "btc-technical-analysis"
        assert data["identity"]["node_id"] == "node-abc123"
        assert data["identity"]["agent_id"] == 42

    def test_get_manifest_not_found(self, test_app):
        resp = test_app.get("/api/v1/agents/nonexistent-node/manifest")
        assert resp.status_code == 404

    def test_manifest_has_trust_section(self, test_app):
        resp = test_app.get("/api/v1/agents/node-abc123/manifest")
        data = resp.json()
        assert "trust" in data
        assert data["trust"]["type"] == "b1e55ed-karma"


class TestWellKnownEndpoint:
    def test_well_known_agent_registration(self, test_app):
        resp = test_app.get("/.well-known/agent-registration.json")
        assert resp.status_code == 200
        data = resp.json()
        assert "registration" in data["type"]  # accept both EIP URL and internal spec URL
        assert data["name"] == "b1e55ed"
        # manifest uses supportedTrust + endpoints instead of capabilities dict
        assert "supportedTrust" in data or "capabilities" in data
        assert len(data.get("endpoints", [])) > 0

    def test_well_known_has_operator(self, test_app):
        resp = test_app.get("/.well-known/agent-registration.json")
        data = resp.json()
        # manifest uses links.github instead of operator.repo
        assert "links" in data or "operator" in data


# ---------------------------------------------------------------------------
# DB migration test
# ---------------------------------------------------------------------------


class TestDBMigration:
    def test_contributors_has_agent_id_column(self):
        from engine.core.database import Database

        db = Database(":memory:")
        cols = [str(r[1]) for r in db.conn.execute("PRAGMA table_info(contributors)").fetchall()]
        assert "agent_id" in cols
        assert "chain_tx_hash" in cols

    def test_agent_id_is_nullable(self):
        """agent_id should be NULL by default for existing contributors."""
        from engine.core.database import Database

        db = Database(":memory:")
        db.execute(
            "INSERT INTO contributors (id, node_id, name, role, registered_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("test-1", "node-1", "test", "agent", "2025-01-01", "2025-01-01"),
        )
        db.conn.commit()
        row = db.execute("SELECT agent_id, chain_tx_hash FROM contributors WHERE id = ?", ("test-1",)).fetchone()
        assert row["agent_id"] is None
        assert row["chain_tx_hash"] is None


# ---------------------------------------------------------------------------
# ContributorRegistry chain_client integration
# ---------------------------------------------------------------------------


class TestContributorRegistryChainWiring:
    def test_register_without_chain_client(self):
        """Registration works fine without a chain client."""
        from engine.core.contributors import ContributorRegistry
        from engine.core.database import Database

        db = Database(":memory:")
        reg = ContributorRegistry(db)
        c = reg.register(node_id="node-test", name="test-producer", role="agent")
        assert c.node_id == "node-test"

    def test_register_with_noop_chain_client(self):
        """When chain_client.register_producer returns None, registration still succeeds."""
        from unittest.mock import MagicMock

        from engine.core.contributors import ContributorRegistry
        from engine.core.database import Database

        db = Database(":memory:")
        mock_chain = MagicMock()
        mock_chain.register_producer.return_value = None

        reg = ContributorRegistry(db, chain_client=mock_chain)
        c = reg.register(node_id="node-chain-test", name="chain-producer", role="agent")
        assert c.node_id == "node-chain-test"
        mock_chain.register_producer.assert_called_once()

    def test_register_with_chain_client_sets_agent_id(self):
        """When chain_client returns an agent_id, it gets stored in DB."""
        from unittest.mock import MagicMock

        from engine.core.contributors import ContributorRegistry
        from engine.core.database import Database

        db = Database(":memory:")
        mock_chain = MagicMock()
        mock_chain.register_producer.return_value = 99

        reg = ContributorRegistry(db, chain_client=mock_chain)
        c = reg.register(node_id="node-onchain", name="onchain-producer", role="agent")
        assert c.node_id == "node-onchain"

        # Chain registration is now asynchronous (background thread); wait briefly.
        import time

        time.sleep(0.2)

        # Verify agent_id was written to DB
        row = db.execute("SELECT agent_id FROM contributors WHERE node_id = ?", ("node-onchain",)).fetchone()
        assert row["agent_id"] == 99

    def test_register_chain_exception_does_not_block(self):
        """If chain_client raises, registration still succeeds."""
        from unittest.mock import MagicMock

        from engine.core.contributors import ContributorRegistry
        from engine.core.database import Database

        db = Database(":memory:")
        mock_chain = MagicMock()
        mock_chain.register_producer.side_effect = RuntimeError("RPC down")

        reg = ContributorRegistry(db, chain_client=mock_chain)
        c = reg.register(node_id="node-error", name="error-producer", role="agent")
        assert c.node_id == "node-error"
