"""engine.integrations.eas

Ethereum Attestation Service (EAS) client for b1e55ed contributor registry.

Design goals:
- Lightweight: no web3 dependency.
- Off-chain attestations (EIP-712 signed) for zero-gas contributor registration.
- Best-effort integration: EAS failures must never block local registration.

This module intentionally implements only a minimal subset.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ZERO_BYTES32 = "0x" + "00" * 32


def _require_eth_account() -> None:
    try:
        import eth_account  # noqa: F401
    except Exception as e:  # pragma: no cover
        raise RuntimeError("EAS support requires eth-account (install with: pip install b1e55ed[eas])") from e


def _norm_hex32(v: str) -> str:
    s = str(v)
    if not s.startswith("0x"):
        s = "0x" + s
    if len(s) != 66:
        raise ValueError(f"expected 32-byte hex string, got {v}")
    return s.lower()


def _norm_addr(v: str) -> str:
    s = str(v)
    if not s.startswith("0x"):
        s = "0x" + s
    if len(s) != 42:
        raise ValueError(f"expected address hex string, got {v}")
    return s.lower()


def _keccak_bytes(data: bytes) -> bytes:
    try:
        from eth_utils.crypto import keccak
    except Exception as e:  # pragma: no cover
        raise RuntimeError("EAS support requires eth-utils") from e
    return keccak(data)


@dataclass(frozen=True)
class AttestationData:
    schema_uid: str
    recipient: str  # 0x address or 0x0 for no recipient
    data: dict[str, Any]  # Attestation payload (domain-specific)
    revocable: bool = True
    ref_uid: str = ""  # Reference to another attestation
    expiration: int = 0  # 0 = no expiration


@dataclass(frozen=True)
class Attestation:
    uid: str
    schema_uid: str
    attester: str
    recipient: str
    data: dict[str, Any]
    time: int
    revocable: bool
    onchain: bool


class EASClient:
    """Lightweight EAS client using raw JSON-RPC (no web3 dependency)."""

    def __init__(
        self,
        *,
        rpc_url: str,
        eas_address: str,
        schema_registry_address: str,
        private_key: str = "",
        chain_id: int = 1,
    ):
        self._rpc_url = str(rpc_url)
        self._eas = _norm_addr(eas_address)
        self._schema_registry = _norm_addr(schema_registry_address)
        self._private_key = str(private_key)
        self._chain_id = int(chain_id)
        self._http = httpx.Client(timeout=30)

    def register_schema(self, schema: str, *, resolver: str = ZERO_ADDRESS, revocable: bool = True) -> str:
        raise NotImplementedError("Schema registration should be done manually via etherscan or deployment script")

    def _eip712_typed_data(
        self,
        *,
        schema_uid: str,
        recipient: str,
        attested_at: int,
        expiration: int,
        revocable: bool,
        ref_uid: str,
        payload_bytes: bytes,
    ) -> dict[str, Any]:
        return {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "Attestation": [
                    {"name": "schema", "type": "bytes32"},
                    {"name": "recipient", "type": "address"},
                    {"name": "time", "type": "uint64"},
                    {"name": "expirationTime", "type": "uint64"},
                    {"name": "revocable", "type": "bool"},
                    {"name": "refUID", "type": "bytes32"},
                    {"name": "data", "type": "bytes"},
                ],
            },
            "primaryType": "Attestation",
            "domain": {
                "name": "EAS Attestation",
                "version": "1.0",
                "chainId": int(self._chain_id),
                "verifyingContract": self._eas,
            },
            "message": {
                "schema": _norm_hex32(schema_uid),
                "recipient": _norm_addr(recipient),
                "time": int(attested_at),
                "expirationTime": int(expiration),
                "revocable": bool(revocable),
                "refUID": _norm_hex32(ref_uid),
                "data": payload_bytes,
            },
        }

    def create_offchain_attestation(self, data: AttestationData) -> dict[str, Any]:
        """Create a signed off-chain attestation.

        Returns a JSON-serializable signed object.
        """

        _require_eth_account()
        if not self._private_key:
            raise ValueError("attester private_key is required to create off-chain attestations")

        from eth_account import Account
        from eth_account.messages import encode_typed_data

        acct = Account.from_key(self._private_key)
        attester = str(acct.address).lower()

        ts = int(time.time())
        ref = data.ref_uid or ZERO_BYTES32

        payload_bytes = json.dumps(data.data, sort_keys=True, separators=(",", ":")).encode("utf-8")

        typed = self._eip712_typed_data(
            schema_uid=data.schema_uid,
            recipient=data.recipient,
            attested_at=ts,
            expiration=int(data.expiration or 0),
            revocable=bool(data.revocable),
            ref_uid=ref,
            payload_bytes=payload_bytes,
        )

        msg = encode_typed_data(full_message=typed)
        sig = Account.sign_message(msg, private_key=self._private_key).signature
        sig_hex = "0x" + sig.hex()

        uid = "0x" + _keccak_bytes(sig).hex()

        return {
            "uid": uid,
            "schema_uid": _norm_hex32(data.schema_uid),
            "attester": attester,
            "recipient": _norm_addr(data.recipient),
            "time": ts,
            "expiration": int(data.expiration or 0),
            "revocable": bool(data.revocable),
            "ref_uid": _norm_hex32(ref),
            "data": json.loads(payload_bytes.decode("utf-8")),
            "data_bytes": "0x" + payload_bytes.hex(),
            "signature": sig_hex,
            "eip712": {
                "domain": typed["domain"],
                "types": typed["types"],
                "primaryType": typed["primaryType"],
                # message is not included here because `data` is bytes; we include both
                # a decoded dict (`data`) and hex (`data_bytes`) for verifiers.
                "message": {
                    **{k: v for k, v in typed["message"].items() if k != "data"},
                    "data": "0x" + payload_bytes.hex(),
                },
            },
            "onchain": False,
        }

    def verify_offchain_attestation(self, attestation: dict[str, Any]) -> bool:
        _require_eth_account()

        from eth_account import Account
        from eth_account.messages import encode_typed_data

        try:
            sig_hex = str(attestation.get("signature") or "")
            sig = bytes.fromhex(sig_hex.removeprefix("0x"))

            schema_uid = _norm_hex32(str(attestation.get("schema_uid") or ""))
            recipient = _norm_addr(str(attestation.get("recipient") or ZERO_ADDRESS))
            ts = int(attestation.get("time") or 0)
            expiration = int(attestation.get("expiration") or 0)
            revocable = bool(attestation.get("revocable") is True)
            ref_uid = _norm_hex32(str(attestation.get("ref_uid") or ZERO_BYTES32))

            data_bytes_hex = str(attestation.get("data_bytes") or "")
            payload_bytes = bytes.fromhex(data_bytes_hex.removeprefix("0x"))

            typed = self._eip712_typed_data(
                schema_uid=schema_uid,
                recipient=recipient,
                attested_at=ts,
                expiration=expiration,
                revocable=revocable,
                ref_uid=ref_uid,
                payload_bytes=payload_bytes,
            )
            msg = encode_typed_data(full_message=typed)
            recovered = str(Account.recover_message(msg, signature=sig)).lower()
            attester = str(attestation.get("attester") or "").lower()

            if not attester:
                return False
            return recovered == attester
        except Exception:
            return False

    def create_onchain_attestation(self, data: AttestationData) -> str:
        raise NotImplementedError("On-chain attestations are not implemented in the lightweight client")

    def get_attestation(self, uid: str) -> Attestation | None:
        _ = uid
        raise NotImplementedError("Reading on-chain attestations is not implemented in the lightweight client")

    def get_attestations_by_schema(self, schema_uid: str, *, limit: int = 100) -> list[Attestation]:
        _ = (schema_uid, limit)
        raise NotImplementedError("Indexer-based listing is not implemented in the lightweight client")

    def rpc_call(self, method: str, params: list[object]) -> Any:
        """Raw JSON-RPC helper (used in unit tests with mocked responses)."""

        payload = {"jsonrpc": "2.0", "id": 1, "method": str(method), "params": list(params)}
        r = self._http.post(self._rpc_url, json=payload)
        r.raise_for_status()
        out = r.json()
        if "error" in out:
            raise RuntimeError(str(out["error"]))
        return out.get("result")
