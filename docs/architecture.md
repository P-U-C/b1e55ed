# Architecture Overview

b1e55ed is an event-sourced signal engine. Producers emit events. The brain reads events and emits events. Execution reads events and emits events.

## High-level diagram

```text
Producers (internal + registered) ──────────────────────┐
                                                         │
Curator Pipeline (operator intel → structured signals) ──┤
                                                         ▼
                                                   Event Store
                                                  (SQLite + hash chain)
                                                         │
                                           ┌─────────────┼──────────────┐
                                           ▼             ▼              ▼
                                         Brain       Backtest       Oracle
                                    (synthesis,    (walk-forward, (provenance
                                     learning,      gridsweep,    projection,
                                     regime)        megasweep)    no auth)
                                           │
                                    Kill Switch
                                           │
                                       Execution
                                    (paper/live, Kelly)
                                           │
                              ┌────────────┼────────────────┐
                              ▼            ▼                ▼
                             CLI          REST           Dashboard
                        (authoritative)  (/api/v1/*)    (read-only)
                                         │
                                         ├────── MCP server
                                         ├────── SSE stream
                                         └────── Oracle endpoint (public)
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

## Curator Pipeline

Operator intel enters the system through the curator pipeline.

- CLI: `b1e55ed signal "<text>" [--symbols] [--direction] [--conviction]`
- API: `POST /api/v1/signals/submit`
- Signals are attributed to contributors via `node_id`
- Weight in synthesis: `weights.curator` (default 0.25)

See: [curator.md](curator.md).

## Backtest Engine

The backtest engine reads from the event store and validates strategies against historical data.

- Walk-forward validation with FDR correction
- Regime-conditioned results (EARLY_BULL, LATE_BULL, BEAR, SIDEWAYS)
- Dynamic Kelly sizing: `b1e55ed kelly`

See: [backtest.md](backtest.md).

## Agent Interfaces

Three interfaces for AI agents:

| Interface | Endpoint | Auth |
|-----------|----------|------|
| SSE stream | `GET /api/v1/events/stream` | Required |
| MCP server | `POST /api/v1/mcp` | Required |
| Oracle | `GET /api/v1/oracle/producers/{id}/provenance` | None |

See: [agent-interfaces.md](agent-interfaces.md).

## Oracle

The oracle is a read-only projection layer over the event store. It answers whether a signal producer has verifiable history. No authentication required.

See: [oracle.md](oracle.md).

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
- MCP server: `POST /api/v1/mcp` (JSON-RPC 2.0).
- SSE stream: `GET /api/v1/events/stream`.
- Oracle: `GET /api/v1/oracle/producers/{id}/provenance` (no auth).

See: [api-reference.md](api-reference.md).
