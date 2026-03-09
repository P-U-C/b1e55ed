"""Tests for CouncilChainPoster — ERC-8004 Validation Registry posting.

All tests are self-contained: no live chain calls, no network required.
"""

from __future__ import annotations

import hashlib
import json
from unittest.mock import MagicMock

from engine.review.chain_verdicts import CouncilChainPoster

# ---------------------------------------------------------------------------
# Fixture: sample verdict payload
# ---------------------------------------------------------------------------

SAMPLE_VERDICT_JSON = {
    "verdict": "pass",
    "pr_number": 123,
    "reviewers": {
        "correctness": {"disposition": "pass", "confidence": 0.95},
        "epistemics": {"disposition": "pass", "confidence": 0.88},
    },
    "arbiter": {"final_verdict": "pass", "reasoning": "All checks passed."},
}


# ---------------------------------------------------------------------------
# Test: chain_client=None → no-op
# ---------------------------------------------------------------------------


class TestCouncilChainPosterNoop:
    """When chain_client is None, post_verdict returns None silently."""

    def test_post_verdict_returns_none_when_no_client(self):
        poster = CouncilChainPoster(chain_client=None)
        result = poster.post_verdict(
            verdict="pass",
            pr_number=42,
            pr_url="https://github.com/P-U-C/b1e55ed/pull/42",
            verdict_json=SAMPLE_VERDICT_JSON,
        )
        assert result is None

    def test_post_verdict_no_exception_when_no_client(self):
        """Ensure no exception is raised even with unusual inputs."""
        poster = CouncilChainPoster(chain_client=None, system_agent_id=99)
        # Should not raise
        result = poster.post_verdict(
            verdict="block",
            pr_number=0,
            pr_url="",
            verdict_json={},
        )
        assert result is None


# ---------------------------------------------------------------------------
# Test: mocked chain_client → correct args
# ---------------------------------------------------------------------------


class TestCouncilChainPosterMocked:
    """With a mocked chain_client, verify correct call signatures."""

    def test_post_verdict_calls_post_validation(self):
        mock_client = MagicMock()
        mock_client.post_validation.return_value = "0xdeadbeef"

        poster = CouncilChainPoster(chain_client=mock_client, system_agent_id=7)
        tx = poster.post_verdict(
            verdict="pass",
            pr_number=123,
            pr_url="https://github.com/P-U-C/b1e55ed/pull/123",
            verdict_json=SAMPLE_VERDICT_JSON,
        )

        assert tx == "0xdeadbeef"
        mock_client.post_validation.assert_called_once()

        call_kwargs = mock_client.post_validation.call_args
        # Verify positional/keyword args
        assert call_kwargs.kwargs["agent_id"] == 7
        assert call_kwargs.kwargs["verdict"] == "pass"
        assert call_kwargs.kwargs["result_uri"] == "https://github.com/P-U-C/b1e55ed/pull/123"
        assert len(call_kwargs.kwargs["result_hash"]) == 32

    def test_post_verdict_uses_system_agent_id(self):
        mock_client = MagicMock()
        mock_client.post_validation.return_value = "0xabc"

        poster = CouncilChainPoster(chain_client=mock_client, system_agent_id=42)
        poster.post_verdict(
            verdict="concern",
            pr_number=99,
            pr_url="https://github.com/P-U-C/b1e55ed/pull/99",
            verdict_json={"verdict": "concern"},
        )

        call_kwargs = mock_client.post_validation.call_args
        assert call_kwargs.kwargs["agent_id"] == 42

    def test_post_verdict_returns_none_on_chain_failure(self):
        mock_client = MagicMock()
        mock_client.post_validation.return_value = None

        poster = CouncilChainPoster(chain_client=mock_client, system_agent_id=0)
        result = poster.post_verdict(
            verdict="block",
            pr_number=200,
            pr_url="https://github.com/P-U-C/b1e55ed/pull/200",
            verdict_json={"verdict": "block"},
        )
        assert result is None

    def test_post_verdict_catches_exception(self):
        mock_client = MagicMock()
        mock_client.post_validation.side_effect = RuntimeError("RPC down")

        poster = CouncilChainPoster(chain_client=mock_client, system_agent_id=0)
        # Should not raise
        result = poster.post_verdict(
            verdict="pass",
            pr_number=300,
            pr_url="https://github.com/P-U-C/b1e55ed/pull/300",
            verdict_json=SAMPLE_VERDICT_JSON,
        )
        assert result is None


# ---------------------------------------------------------------------------
# Test: verdict hash properties
# ---------------------------------------------------------------------------


class TestVerdictHash:
    """Verify hash computation is deterministic and correct length."""

    def test_verdict_hash_is_32_bytes(self):
        h = CouncilChainPoster.compute_verdict_hash(SAMPLE_VERDICT_JSON)
        assert isinstance(h, bytes)
        assert len(h) == 32

    def test_verdict_hash_deterministic(self):
        h1 = CouncilChainPoster.compute_verdict_hash(SAMPLE_VERDICT_JSON)
        h2 = CouncilChainPoster.compute_verdict_hash(SAMPLE_VERDICT_JSON)
        assert h1 == h2

    def test_verdict_hash_key_order_independent(self):
        """JSON keys are sorted, so insertion order doesn't matter."""
        d1 = {"z": 1, "a": 2, "m": 3}
        d2 = {"a": 2, "m": 3, "z": 1}
        assert CouncilChainPoster.compute_verdict_hash(d1) == CouncilChainPoster.compute_verdict_hash(d2)

    def test_verdict_hash_uses_sha3_256(self):
        """Verify hash matches direct SHA3-256 computation."""
        raw = json.dumps(SAMPLE_VERDICT_JSON, sort_keys=True).encode()
        expected = hashlib.sha3_256(raw).digest()[:32]
        actual = CouncilChainPoster.compute_verdict_hash(SAMPLE_VERDICT_JSON)
        assert actual == expected

    def test_verdict_hash_different_for_different_inputs(self):
        h1 = CouncilChainPoster.compute_verdict_hash({"verdict": "pass"})
        h2 = CouncilChainPoster.compute_verdict_hash({"verdict": "block"})
        assert h1 != h2

    def test_empty_dict_hash(self):
        h = CouncilChainPoster.compute_verdict_hash({})
        assert isinstance(h, bytes)
        assert len(h) == 32


# ---------------------------------------------------------------------------
# Test: result_uri contains PR number
# ---------------------------------------------------------------------------


class TestResultUri:
    """Verify result_uri is correctly constructed from pr_url."""

    def test_result_uri_is_pr_url(self):
        mock_client = MagicMock()
        mock_client.post_validation.return_value = "0x123"

        poster = CouncilChainPoster(chain_client=mock_client)
        poster.post_verdict(
            verdict="pass",
            pr_number=456,
            pr_url="https://github.com/P-U-C/b1e55ed/pull/456",
            verdict_json=SAMPLE_VERDICT_JSON,
        )

        call_kwargs = mock_client.post_validation.call_args
        result_uri = call_kwargs.kwargs["result_uri"]
        assert "456" in result_uri
        assert result_uri == "https://github.com/P-U-C/b1e55ed/pull/456"


# ---------------------------------------------------------------------------
# Test: constructor properties
# ---------------------------------------------------------------------------


class TestCouncilChainPosterProperties:
    def test_default_system_agent_id(self):
        poster = CouncilChainPoster(chain_client=None)
        assert poster.system_agent_id == 0

    def test_custom_system_agent_id(self):
        poster = CouncilChainPoster(chain_client=None, system_agent_id=42)
        assert poster.system_agent_id == 42

    def test_chain_client_property(self):
        mock = MagicMock()
        poster = CouncilChainPoster(chain_client=mock)
        assert poster.chain_client is mock

    def test_chain_client_none(self):
        poster = CouncilChainPoster(chain_client=None)
        assert poster.chain_client is None


# ---------------------------------------------------------------------------
# Test: OnChainConfig system_agent_id field
# ---------------------------------------------------------------------------


class TestOnChainConfigSystemAgentId:
    def test_default_system_agent_id(self):
        from engine.core.config import OnChainConfig

        cfg = OnChainConfig()
        assert cfg.system_agent_id == 0

    def test_custom_system_agent_id(self):
        from engine.core.config import OnChainConfig

        cfg = OnChainConfig(system_agent_id=99)
        assert cfg.system_agent_id == 99


# ---------------------------------------------------------------------------
# Test: system manifest includes validation capability
# ---------------------------------------------------------------------------


class TestSystemManifestValidation:
    def test_manifest_has_validation_capability(self):
        from api.routes.agents import build_system_manifest

        manifest = build_system_manifest(api_base="https://oracle.b1e55ed.example.com")
        assert manifest["capabilities"]["validation"] is True

    def test_manifest_supported_trust_includes_validation(self):
        from api.routes.agents import build_system_manifest

        manifest = build_system_manifest()
        assert "supportedTrust" in manifest
        assert "reputation" in manifest["supportedTrust"]
        assert "validation" in manifest["supportedTrust"]
