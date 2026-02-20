# b1e55ed

<p align="center">
  <img src="assets/b1e55ed-hero.jpg" alt="b1e55ed" width="900" />
</p>

**b1e55ed** (0xb1e55ed = "blessed") — a sovereign trading intelligence system with compound learning.

Built around one primitive: **events**. Producers emit events. The brain reads events and emits events. Execution reads events and emits events. An append-only hash chain makes the system auditable by construction.

[![Tests](https://github.com/P-U-C/b1e55ed/workflows/CI/badge.svg)](https://github.com/P-U-C/b1e55ed/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Features

- Event-sourced core (append-only DB + hash chain)
- Kill switch gating (operator override)
- CLI control plane (tables or JSON)
- REST API mounted under `/api/v1/`
- Dashboard (read-oriented)
- Dynamic producer registration
- Contributors (registry, scoring, leaderboard)
- Signal attribution (`/api/v1/signals/submit`)
- The Forge (Ethereum-prefixed identity derivation)
- EAS integration (optional off-chain attestations)
- Webhook dispatch (CLI-managed subscriptions)
- Karma / treasury accounting

## Installation

### From source

```bash
git clone https://github.com/P-U-C/b1e55ed.git
cd b1e55ed
uv sync
```

## Quick start

Sequence: forge identity → setup → register contributor → run brain.

```bash
export B1E55ED_MASTER_PASSWORD="your-secure-password"
uv run b1e55ed identity forge
uv run b1e55ed setup
uv run b1e55ed contributors register --name "local-operator" --role operator
uv run b1e55ed brain
```

Start API + dashboard:

```bash
export B1E55ED_API__AUTH_TOKEN="your-secret-token"
uv run b1e55ed api
uv run b1e55ed dashboard
```

- API: `http://localhost:5050/api/v1/health`
- Dashboard: `http://localhost:5051`

## Contributors

Contributors are the attribution unit for signals. They are used for:

- signal provenance (`contributor_id`)
- contributor scoring and leaderboard
- optional EAS attestations

Docs: [docs/contributors.md](docs/contributors.md)

## The Forge

The Forge derives an Ethereum identity with a `0xb1e55ed` prefix.

Docs:
- [docs/FORGE_SPEC.md](docs/FORGE_SPEC.md)
- [docs/getting-started.md](docs/getting-started.md)

## EAS integration

EAS integration is optional and supports off-chain attestations.

Docs: [docs/eas-integration.md](docs/eas-integration.md)

## Documentation

- [Getting Started](docs/getting-started.md)
- [Configuration](docs/configuration.md)
- [CLI reference](docs/cli-reference.md)
- [API reference](docs/api-reference.md)
- [Contributors](docs/contributors.md)
- [Architecture](docs/architecture.md)
- [Security](docs/security.md)
- [Deployment](docs/deployment.md)

## Development

### Tests

```bash
# 196+ tests
uv run pytest -q
```

### Lint and format

```bash
uv run ruff check engine/ api/ tests/
uv run ruff format engine/ api/ tests/
```

## License

MIT
