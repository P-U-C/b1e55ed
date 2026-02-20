# Contributors

Contributors are the attribution unit for b1e55ed.

A contributor represents a human operator or an agent process that can submit signals or otherwise influence decisions.

Roles:
- `operator`
- `agent`
- `tester`
- `curator`

## Identity model

b1e55ed uses two identities:

1. Local node identity (Ed25519)
   - Stored at `~/.b1e55ed/identity.key`
   - Used by the engine security layer

2. Forged Ethereum identity (The Forge)
   - Stored at `.b1e55ed/identity.json`
   - Used for Ethereum-facing integrations (EAS) and network identity

The contributor registry references a stable `node_id` string.

## Registration

### CLI

List contributors:

```bash
b1e55ed contributors list
b1e55ed contributors list --json
```

Register:

```bash
b1e55ed contributors register --name "alice" --role operator
```

Register and create an EAS off-chain attestation (optional):

```bash
b1e55ed contributors register --name "alice" --role operator --attest
```

Remove:

```bash
b1e55ed contributors remove --id <contributor_id>
```

### API

Register:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"node_id":"b1e55ed-deadbeef","name":"alice","role":"operator","metadata":{}}' \
  http://localhost:5050/api/v1/contributors/register
```

List:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:5050/api/v1/contributors/
```

## Signal attribution

Signals can be attributed to contributors via:

- `POST /api/v1/signals/submit`

The submit endpoint:
- resolves a contributor by `node_id`
- writes the signal event
- records attribution in `contributor_signals`

This path is intended for external operator layers and agent producers.

## EAS attestations

If EAS is enabled, b1e55ed can create an off-chain attestation for a contributor and store:

- `metadata.eas.uid`
- `metadata.eas.attestation`

Useful commands:

```bash
b1e55ed eas status
b1e55ed eas verify --uid <uid>
```

See: [eas-integration.md](eas-integration.md).

## Reputation scoring

Contributor scoring is computed from locally observed outcomes.

The scoring output includes:
- signals submitted / accepted / profitable
- hit rate
- streak
- karma attribution
- final score

CLI:

```bash
b1e55ed contributors score --id <contributor_id>
b1e55ed contributors leaderboard --limit 20
```

API:
- `GET /api/v1/contributors/{id}/score`
- `GET /api/v1/contributors/leaderboard`

## Leaderboard

The leaderboard is a projection over the scoring model.

Use it for routing decisions, automated weighting, and operator review.

## Network readiness (future)

Planned direction:
- peer discovery via on-chain registry
- contributor identity anchored by attestations
- portable reputation proofs
