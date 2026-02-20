# Architecture Overview

b1e55ed is an event-sourced signal engine. Producers emit events. The brain reads events and emits events. Execution reads events and emits events.

## High-level diagram

```text
                ┌───────────────────────────────┐
                │            The Forge           │
                │  Ethereum-prefixed identity    │
                └───────────────┬───────────────┘
                                │
                                │ (optional)
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Contributor layer (C1)                       │
│  - Contributor registry (node_id → contributor_id)               │
│  - Attribution tables (signals submitted/accepted/profitable)    │
│  - Scoring + leaderboard                                         │
│  - Optional EAS off-chain attestations                           │
└─────────────────────────────────────────────────────────────────┘

┌───────────────────────────────┐       ┌─────────────────────────┐
│          Producers             │       │        Operators         │
│  - internal producers          │       │  - humans/agents         │
│  - registered producers        │       │  - submit curator intel  │
└───────────────┬───────────────┘       └─────────────┬───────────┘
                │                                     │
                ▼                                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Event store (SQLite)                      │
│  - append-only events table                                       │
│  - hash chain integrity                                           │
│  - projections: positions, regime, alerts                         │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                              Brain                               │
│  - orchestrator (run_cycle)                                       │
│  - kill switch gating                                              │
│  - regime detection                                                │
│  - intent generation + settlement workflow                         │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                           Execution                               │
│  - paper/live mode                                                 │
│  - position tracking                                               │
│  - karma intents                                                   │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Interfaces (control plane)                    │
│  - CLI (authoritative)                                             │
│  - REST API (/api/v1/*)                                            │
│  - Dashboard (read-oriented)                                       │
│  - Webhooks (event dispatch; CLI-managed)                          │
└─────────────────────────────────────────────────────────────────┘
```

## Contributor layer

### Registry

- Stored in the local database.
- `node_id` is the stable external identity; `contributor_id` is the internal primary key.
- Signals can be attributed to contributors through `POST /api/v1/signals/submit`.

### Scoring

Contributor scoring is computed from event outcomes and attribution tables.

Reference modules:
- `engine/core/contributors.py`
- `engine/core/scoring.py`

## The Forge

The Forge derives an Ethereum identity with a `0xb1e55ed` prefix.

- Used as the preferred identity for on-chain or off-chain attestations.
- Separate from the local Ed25519 node identity used by the security layer.

Reference module:
- `engine/integrations/forge.py`

## EAS integration

EAS attestations are optional.

Attestation flow (off-chain mode):

```text
Contributor registration
  → (optional) create off-chain EAS attestation
  → store attestation + UID in contributor.metadata.eas
  → verify locally via `b1e55ed eas verify --uid <uid>`
```

Reference module:
- `engine/integrations/eas.py`

See: [eas-integration.md](eas-integration.md).

## Webhook dispatch

Webhook subscriptions are stored in the local database and matched against event types using glob patterns.

- Delivery is best-effort.
- Dispatch is non-blocking relative to event persistence.
- Management is CLI-first (`b1e55ed webhooks ...`).

Reference module:
- `engine/core/webhooks.py`

## Producer registration

Producers exist in two forms:
- Built-in producers (discovered at runtime).
- Dynamic producer registrations stored in the database and visible to the API/CLI.

Reference modules:
- `api/routes/producers.py`
- `engine/cli.py` (producers subcommands)

## Interface surface

- REST API: `api/main.py` mounts the router at `/api/v1`.
- CLI: `engine/cli.py` is the authoritative command surface.

See: [api-reference.md](api-reference.md).
