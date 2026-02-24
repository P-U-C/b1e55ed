"""tests.unit.test_contributor_github_publish

Unit tests for the GitHub publish hook in ContributorRegistry.register().
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


def _make_eas_client() -> MagicMock:
    """Return a mock EAS client that produces a fake attestation."""
    mock = MagicMock()
    mock.create_offchain_attestation.return_value = FAKE_ATTESTATION
    return mock


def test_register_with_attest_and_publish(tmp_path: Path) -> None:
    """EAS + publisher both succeed → meta.eas.publish.github is populated."""
    db = Database(tmp_path / "brain.db")
    eas_mock = _make_eas_client()
    publisher_result = {
        "issue_url": "https://github.com/owner/repo/issues/1",
        "issue_number": 1,
        "owner": "owner",
        "repo": "repo",
    }
    publisher_mock = MagicMock(return_value=publisher_result)

    reg = ContributorRegistry(db, eas_client=eas_mock, github_publisher=publisher_mock)
    c = reg.register(
        node_id="node-pub-1",
        name="Bob",
        role="operator",
        metadata={"eas": {"schema_uid": "0xschema"}},
        attest=True,
    )

    assert isinstance(c.metadata.get("eas"), dict)
    eas_meta = c.metadata["eas"]
    assert eas_meta.get("uid") == "0xabcdef"
    assert eas_meta.get("attestation") == FAKE_ATTESTATION
    assert isinstance(eas_meta.get("publish"), dict)
    assert eas_meta["publish"]["github"]["issue_url"] == "https://github.com/owner/repo/issues/1"

    # Publisher was called with the right kwargs
    publisher_mock.assert_called_once()
    call_kwargs = publisher_mock.call_args.kwargs
    assert call_kwargs["contributor_id"] == c.id
    assert call_kwargs["node_id"] == "node-pub-1"
    assert call_kwargs["name"] == "Bob"
    assert call_kwargs["role"] == "operator"
    assert call_kwargs["attestation"] == FAKE_ATTESTATION


def test_register_publish_failure_still_registers(tmp_path: Path) -> None:
    """Publisher raises → contributor is still registered with uid but no publish key."""
    db = Database(tmp_path / "brain.db")
    eas_mock = _make_eas_client()
    publisher_mock = MagicMock(side_effect=RuntimeError("GitHub down"))

    reg = ContributorRegistry(db, eas_client=eas_mock, github_publisher=publisher_mock)
    c = reg.register(
        node_id="node-pub-2",
        name="Carol",
        role="agent",
        metadata={"eas": {"schema_uid": "0xschema"}},
        attest=True,
    )

    # Contributor was persisted
    assert c.id
    assert reg.get(c.id) is not None

    eas_meta = c.metadata.get("eas")
    assert isinstance(eas_meta, dict)
    assert eas_meta.get("uid") == "0xabcdef"  # EAS still worked

    # No publish data (publisher failed gracefully)
    assert "publish" not in eas_meta


def test_register_no_attest_skips_publisher(tmp_path: Path) -> None:
    """attest=False → publisher is never called."""
    db = Database(tmp_path / "brain.db")
    publisher_mock = MagicMock()

    reg = ContributorRegistry(db, github_publisher=publisher_mock)
    c = reg.register(
        node_id="node-pub-3",
        name="Dave",
        role="tester",
        metadata={},
        attest=False,
    )

    assert c.id
    publisher_mock.assert_not_called()


def test_register_eas_fails_skips_publisher(tmp_path: Path) -> None:
    """EAS fails → uid is absent → publisher is never called."""
    db = Database(tmp_path / "brain.db")

    eas_mock = MagicMock()
    eas_mock.create_offchain_attestation.side_effect = Exception("EAS exploded")
    publisher_mock = MagicMock()

    reg = ContributorRegistry(db, eas_client=eas_mock, github_publisher=publisher_mock)
    c = reg.register(
        node_id="node-pub-4",
        name="Eve",
        role="curator",
        metadata={},
        attest=True,
    )

    assert c.id
    publisher_mock.assert_not_called()


def test_register_publisher_returns_none_gracefully(tmp_path: Path) -> None:
    """Publisher returns None (e.g. GitHub unavailable) → contributor still fully registered."""
    db = Database(tmp_path / "brain.db")
    eas_mock = _make_eas_client()
    publisher_mock = MagicMock(return_value=None)

    reg = ContributorRegistry(db, eas_client=eas_mock, github_publisher=publisher_mock)
    c = reg.register(
        node_id="node-pub-5",
        name="Frank",
        role="agent",
        metadata={"eas": {"schema_uid": "0xschema"}},
        attest=True,
    )

    assert c.id
    eas_meta = c.metadata.get("eas")
    assert isinstance(eas_meta, dict)
    assert eas_meta.get("uid") == "0xabcdef"
    # No publish sub-dict because publisher returned None
    assert "publish" not in eas_meta
