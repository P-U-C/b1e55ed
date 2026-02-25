"""tests.unit.test_contributor_github_publish

Unit tests for the GitHub publish hook in ContributorRegistry.register().

Publishing fires on every registration when a publisher is configured —
no EAS attestation required. Fail-open: never blocks registration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from engine.core.contributors import ContributorRegistry
from engine.core.database import Database

FAKE_ATTESTATION: dict[str, Any] = {
    "uid": "0xabcdef",
    "schema_uid": "0xschema",
    "attester": "0xattester",
    "recipient": "0x0000",
    "time": 1700000000,
    "expiration": 0,
    "revocable": True,
    "ref_uid": "0x0000",
    "data": {},
    "data_bytes": "0x",
    "signature": "0xsig",
    "onchain": False,
}

_PUBLISHER_RESULT = {
    "issue_url": "https://github.com/owner/repo/issues/1",
    "issue_number": 1,
    "owner": "owner",
    "repo": "repo",
}


def _make_eas_client() -> MagicMock:
    mock = MagicMock()
    mock.create_offchain_attestation.return_value = FAKE_ATTESTATION
    return mock


# ---------------------------------------------------------------------------
# Core behaviour: publisher fires on every registration
# ---------------------------------------------------------------------------


def test_register_without_eas_still_publishes(tmp_path: Path) -> None:
    """Publisher fires even when no EAS client is configured."""
    db = Database(tmp_path / "brain.db")
    publisher_mock = MagicMock(return_value=_PUBLISHER_RESULT)

    reg = ContributorRegistry(db, github_publisher=publisher_mock)
    c = reg.register(node_id="node-1", name="Alice", role="operator", metadata={})

    publisher_mock.assert_called_once()
    call_kwargs = publisher_mock.call_args.kwargs
    assert call_kwargs["node_id"] == "node-1"
    assert call_kwargs["name"] == "Alice"
    assert call_kwargs["role"] == "operator"
    assert call_kwargs["contributor_id"] == c.id

    assert c.metadata.get("publish", {}).get("github", {}).get("issue_url") == _PUBLISHER_RESULT["issue_url"]


def test_register_with_eas_and_publish(tmp_path: Path) -> None:
    """EAS + publisher both succeed → publish result stored at meta.publish.github."""
    db = Database(tmp_path / "brain.db")
    publisher_mock = MagicMock(return_value=_PUBLISHER_RESULT)

    reg = ContributorRegistry(db, eas_client=_make_eas_client(), github_publisher=publisher_mock)
    c = reg.register(
        node_id="node-2",
        name="Bob",
        role="operator",
        metadata={"eas": {"schema_uid": "0xschema"}},
        attest=True,
    )

    # EAS attestation stored
    eas_meta = c.metadata.get("eas", {})
    assert eas_meta.get("uid") == "0xabcdef"
    assert eas_meta.get("attestation") == FAKE_ATTESTATION

    # Publish result at top-level publish key
    pub = c.metadata.get("publish", {})
    assert pub.get("github", {}).get("issue_url") == _PUBLISHER_RESULT["issue_url"]

    # Publisher called with the EAS attestation payload
    call_kwargs = publisher_mock.call_args.kwargs
    assert call_kwargs["attestation"] == FAKE_ATTESTATION


def test_register_without_publisher_no_publish_key(tmp_path: Path) -> None:
    """No publisher configured → no publish key in metadata."""
    db = Database(tmp_path / "brain.db")
    reg = ContributorRegistry(db)
    c = reg.register(node_id="node-3", name="Carol", role="agent", metadata={})
    assert "publish" not in c.metadata


# ---------------------------------------------------------------------------
# Failure modes: fail-open
# ---------------------------------------------------------------------------


def test_register_publish_failure_still_registers(tmp_path: Path) -> None:
    """Publisher raises → contributor is still registered (fail-open)."""
    db = Database(tmp_path / "brain.db")
    publisher_mock = MagicMock(side_effect=RuntimeError("GitHub down"))

    reg = ContributorRegistry(db, github_publisher=publisher_mock)
    c = reg.register(node_id="node-4", name="Dave", role="agent", metadata={})

    assert c.id
    assert reg.get(c.id) is not None
    # No publish key — publisher failed
    assert "publish" not in c.metadata


def test_register_publisher_returns_none_gracefully(tmp_path: Path) -> None:
    """Publisher returns None (e.g. no token) → contributor registered, no publish key."""
    db = Database(tmp_path / "brain.db")
    publisher_mock = MagicMock(return_value=None)

    reg = ContributorRegistry(db, github_publisher=publisher_mock)
    c = reg.register(node_id="node-5", name="Eve", role="curator", metadata={})

    assert c.id
    assert "publish" not in c.metadata


def test_register_eas_fails_publisher_still_fires(tmp_path: Path) -> None:
    """EAS fails → publisher still fires with a synthetic registration record."""
    db = Database(tmp_path / "brain.db")
    eas_mock = MagicMock()
    eas_mock.create_offchain_attestation.side_effect = Exception("EAS exploded")
    publisher_mock = MagicMock(return_value=_PUBLISHER_RESULT)

    reg = ContributorRegistry(db, eas_client=eas_mock, github_publisher=publisher_mock)
    c = reg.register(
        node_id="node-6",
        name="Frank",
        role="operator",
        metadata={},
        attest=True,
    )

    assert c.id
    # Publisher still called despite EAS failure
    publisher_mock.assert_called_once()
    call_kwargs = publisher_mock.call_args.kwargs
    # Synthetic attestation used (no uid from EAS)
    assert "type" in call_kwargs["attestation"] or "uid" in call_kwargs["attestation"]


def test_publisher_called_once_per_registration(tmp_path: Path) -> None:
    """Publisher is called exactly once per registration, not multiple times."""
    db = Database(tmp_path / "brain.db")
    publisher_mock = MagicMock(return_value=_PUBLISHER_RESULT)

    reg = ContributorRegistry(db, github_publisher=publisher_mock)
    reg.register(node_id="node-7a", name="Grace", role="operator", metadata={})
    reg.register(node_id="node-7b", name="Heidi", role="agent", metadata={})

    assert publisher_mock.call_count == 2
