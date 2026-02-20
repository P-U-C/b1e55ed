from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

try:
    import eth_account  # noqa: F401
    import eth_utils  # noqa: F401
except Exception:  # pragma: no cover
    pytest.skip("EAS optional dependencies not installed", allow_module_level=True)

from engine.core.contributors import ContributorRegistry
from engine.core.database import Database
from engine.integrations.eas import AttestationData, EASClient
from engine.integrations.eas_schema import CONTRIBUTOR_SCHEMA, EXPECTED_SCHEMA_HASH, compute_schema_hash


def test_schema_hash_is_stable() -> None:
    assert compute_schema_hash(CONTRIBUTOR_SCHEMA) == EXPECTED_SCHEMA_HASH


def test_offchain_attestation_sign_and_verify(tmp_path: Path) -> None:
    # Deterministic test key (DO NOT USE IN PRODUCTION)
    pk = "0x59c6995e998f97a5a0044966f0945382d1b83f5f8b2e70e9a1baddb5f9d0c2d7"  # anvil default

    client = EASClient(
        rpc_url="http://localhost:8545",
        eas_address="0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587",
        schema_registry_address="0xA7b39296258348C78294F95B872b282326A97BDF",
        private_key=pk,
    )

    att = client.create_offchain_attestation(
        AttestationData(
            schema_uid="0x" + "11" * 32,
            recipient="0x0000000000000000000000000000000000000000",
            data={"nodeId": "node-1", "name": "alice", "role": "operator", "version": "test", "registeredAt": 123},
        )
    )

    assert isinstance(att.get("uid"), str)
    assert str(att["uid"]).startswith("0x")
    assert str(att.get("signature")).startswith("0x")

    assert client.verify_offchain_attestation(att) is True

    # Tamper the signed data bytes => verification should fail
    att2 = json.loads(json.dumps(att))
    att2["data_bytes"] = "0x" + "ff" * 32  # corrupt the signed payload
    assert client.verify_offchain_attestation(att2) is False


def test_rpc_call_with_mocked_http(monkeypatch: pytest.MonkeyPatch) -> None:
    client = EASClient(
        rpc_url="https://example.invalid",
        eas_address="0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587",
        schema_registry_address="0xA7b39296258348C78294F95B872b282326A97BDF",
        private_key="",
    )

    class FakeResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"jsonrpc": "2.0", "id": 1, "result": "0x01"}

    def fake_post(url: str, *, json: dict[str, Any]) -> FakeResp:  # type: ignore[override]
        assert url == "https://example.invalid"
        assert json["method"] == "eth_chainId"
        return FakeResp()

    monkeypatch.setattr(client._http, "post", fake_post)
    assert client.rpc_call("eth_chainId", []) == "0x01"


class FakeEASClient:
    def __init__(self, *, should_fail: bool = False):
        self.should_fail = should_fail

    def create_offchain_attestation(self, data: AttestationData) -> dict[str, Any]:
        if self.should_fail:
            raise RuntimeError("boom")
        return {"uid": "0x" + "ab" * 32, "schema_uid": data.schema_uid, "recipient": data.recipient, "data": data.data, "signature": "0x01", "attester": "0x0"}


def test_contributor_register_with_eas_enabled(tmp_path: Path) -> None:
    db = Database(tmp_path / "brain.db")
    reg = ContributorRegistry(db, eas_client=FakeEASClient())

    c = reg.register(node_id="node-1", name="alice", role="agent", metadata={"eas": {"schema_uid": "0x" + "11" * 32}}, attest=True)
    assert "eas" in c.metadata
    eas_meta = c.metadata["eas"]
    assert isinstance(eas_meta, dict)
    assert str(eas_meta.get("uid")).startswith("0x")
    assert isinstance(eas_meta.get("attestation"), dict)


def test_contributor_register_with_eas_disabled_no_change(tmp_path: Path) -> None:
    db = Database(tmp_path / "brain.db")
    reg = ContributorRegistry(db)

    c = reg.register(node_id="node-1", name="alice", role="agent", metadata={"v": 1}, attest=True)
    assert c.metadata == {"v": 1}


def test_contributor_register_eas_failure_is_fail_open(tmp_path: Path) -> None:
    db = Database(tmp_path / "brain.db")
    reg = ContributorRegistry(db, eas_client=FakeEASClient(should_fail=True))

    c = reg.register(node_id="node-1", name="alice", role="agent", metadata={"v": 1}, attest=True)
    assert c.id
    assert c.metadata.get("v") == 1
