"""engine.integrations.eas_schema

EAS schema definition for b1e55ed contributor registry.

Schema string (Solidity-style):

    bytes32 nodeId, string name, string role, string version, uint64 registeredAt

Manual registration (one-time):

- Register the schema in the Ethereum Attestation Service SchemaRegistry contract
  on Ethereum mainnet:

    SchemaRegistry: 0xA7b39296258348C78294F95B872b282326A97BDF

- Call:

    register(string schema, address resolver, bool revocable)

  with:
    - schema: CONTRIBUTOR_SCHEMA
    - resolver: 0x0000000000000000000000000000000000000000
    - revocable: true

- The returned bytes32 is the schema UID. Store it in config as:

    eas.schema_uid

Notes on schema UID computation:

EAS schema UIDs are computed by the on-chain registry (and depend on resolver
and revocable). For local checks/tests we also compute a deterministic hash of
the schema string (keccak256 of UTF-8 bytes). This can be used to detect
accidental schema changes.
"""

from __future__ import annotations

from dataclasses import dataclass

CONTRIBUTOR_SCHEMA = "bytes32 nodeId, string name, string role, string version, uint64 registeredAt"


def compute_schema_hash(schema: str) -> str:
    """Compute a deterministic hash of the schema string.

    This is *not* guaranteed to match SchemaRegistry's UID for all combinations
    of resolver/revocable, but it is useful as a stable fingerprint.
    """

    try:
        from eth_utils import keccak  # type: ignore[import-not-found]
    except Exception as e:  # pragma: no cover
        raise RuntimeError("eth-utils is required for EAS schema hashing") from e

    h = keccak(text=str(schema))
    return "0x" + h.hex()


EXPECTED_SCHEMA_HASH = compute_schema_hash(CONTRIBUTOR_SCHEMA)


@dataclass(frozen=True, slots=True)
class SchemaInfo:
    schema: str
    expected_hash: str


CONTRIBUTOR_SCHEMA_INFO = SchemaInfo(schema=CONTRIBUTOR_SCHEMA, expected_hash=EXPECTED_SCHEMA_HASH)
