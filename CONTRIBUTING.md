# Contributing

This repository is an event-sourced signal engine.
Changes should be small, auditable, and testable.

## Add a Producer

1. Implement a producer that conforms to the producer interface.
2. Register the producer via CLI or API.

CLI:

```bash
b1e55ed producers register --name <NAME> --domain <DOMAIN> --endpoint <URL> --schedule "*/15 * * * *"
b1e55ed producers list
b1e55ed producers remove --name <NAME>
```

API:

- `POST /api/v1/producers/register`
- `GET /api/v1/producers/`
- `DELETE /api/v1/producers/{name}`

For implementation details and integration contracts, see `SKILL.md`.

## Add a Strategy

1. Implement the strategy interface in the engine.
2. Add the strategy to configuration so it can be selected and parameterized.
3. Add unit tests that pin the strategy’s decision boundary behavior.

## Improve Docs

- Use the public brand vocabulary.
- Prefer “Corpus” over internal terms such as “Grimoire” in public-facing copy.
- Run the full CI suite locally before opening a PR.

## Report Bugs

When opening an issue, include:

- Expected behavior vs observed behavior
- Steps to reproduce
- Version information (`b1e55ed --version`)
- Relevant logs (redact secrets)
- Minimal config snippet if configuration is involved

## Development Setup

Install dependencies:

```bash
uv sync --all-extras
```

Run tests:

```bash
pytest
```

Run lint and formatting:

```bash
ruff check engine/ api/ tests/
ruff format engine/ api/ tests/
```

Run type checks:

```bash
mypy engine/ api/
```

## PR Process

- Branch from `develop`.
- Open PRs targeting `develop`.
- Keep PRs scoped.
- CI must pass (ruff, mypy, pytest).
- Prefer additive changes with explicit tests over implicit behavior changes.
