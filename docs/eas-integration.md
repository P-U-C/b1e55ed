# EAS Integration (Ethereum Attestation Service)

b1e55ed can optionally create **Ethereum Attestation Service (EAS)** attestations when registering contributors.

Why:
- Portable, verifiable contributor registry outside the local SQLite DB
- Off-chain mode is **zero gas** and verifiable by anyone
- Future-proof path to on-chain reputation/karma settlement attestations

## Contracts (Ethereum mainnet)

- **EAS**: `0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587`
- **SchemaRegistry**: `0xA7b39296258348C78294F95B872b282326A97BDF`

## Schema

Contributor schema (Solidity-style string):

```text
bytes32 nodeId, string name, string role, string version, uint64 registeredAt
```

See: `engine/integrations/eas_schema.py`.

## Setup

### 1) Install dependencies

```bash
pip install -e '.[eas]'
```

### 2) Configure

In `config/user.yaml` (or env vars via `B1E55ED_EAS__...`):

```yaml
eas:
  enabled: true
  rpc_url: https://eth.llamarpc.com
  eas_contract: "0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587"
  schema_registry: "0xA7b39296258348C78294F95B872b282326A97BDF"
  schema_uid: "0x..."        # set after schema registration
  attester_private_key: "..." # required for off-chain signing
  mode: offchain              # offchain|onchain
```

### 3) Register schema (manual)

Schema registration is a one-time on-chain action. For now it should be performed manually (Etherscan / script), then the returned `schema_uid` should be stored in config.

## Usage

### CLI

- Show status:

```bash
b1e55ed eas status --json
```

- Register a contributor and also attest:

```bash
b1e55ed contributors register --name Alice --role operator --attest
```

The attestation UID and signed object are stored in contributor `metadata.eas`.

- Verify a stored off-chain attestation:

```bash
b1e55ed eas verify --uid 0x...
```

### API

- List all contributor attestation UIDs:

`GET /api/v1/contributors/attestations`

- Get a contributor’s attestation object:

`GET /api/v1/contributors/{id}/attestation`

## On-chain vs Off-chain

- **Off-chain**: signed EIP-712 payload; zero gas; verifiable by signature recovery.
- **On-chain**: would create a transaction calling EAS; requires gas and nonce management; not implemented in the lightweight client yet.

## External verification

Verifiers can:
1. Fetch the signed attestation object (from API, IPFS, etc.)
2. Reconstruct the EIP-712 typed data payload
3. Recover signer address from signature
4. Compare recovered address to `attester`

## Future extensions

- Reputation milestone attestations
- Karma settlement attestations
- Publishing signed attestations to IPFS or a shared index
