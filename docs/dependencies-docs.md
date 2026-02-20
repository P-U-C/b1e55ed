# Documentation Dependency Graph

Cross-references between documentation files.

Notation:

```text
A → B     A references B
A ⇒ B     A heavily references B
```

## Entry point

```text
README.md
  → docs/getting-started.md
  → docs/configuration.md
  → docs/cli-reference.md
  → docs/api-reference.md
  → docs/contributors.md
  → docs/architecture.md
  → docs/eas-integration.md
  → docs/security.md
  → docs/deployment.md
  → docs/openclaw-integration.md
  → docs/learning-loop.md
  → ROADMAP.md
```

## Core docs

### `docs/getting-started.md`

```text
getting-started.md
  → configuration.md
  → cli-reference.md
  → api-reference.md
  → contributors.md
  → eas-integration.md
  → architecture.md
```

### `docs/cli-reference.md`

```text
cli-reference.md
  → contributors.md
  → eas-integration.md
```

### `docs/api-reference.md`

```text
api-reference.md
  → configuration.md
  → contributors.md
  → eas-integration.md
  → architecture.md
```

### `docs/contributors.md`

```text
contributors.md
  → eas-integration.md
  → api-reference.md
  → cli-reference.md
```

### `docs/configuration.md`

```text
configuration.md
  → eas-integration.md
```

### `docs/architecture.md`

```text
architecture.md
  → api-reference.md
  → contributors.md
  → eas-integration.md
  → dependencies-code.md
```

### `docs/eas-integration.md`

```text
eas-integration.md
  → contributors.md
```

### `docs/security.md`

```text
security.md
  → configuration.md
  → deployment.md
```

### `docs/deployment.md`

```text
deployment.md
  → configuration.md
  → security.md
```

### `docs/dependencies-code.md`

```text
dependencies-code.md
  → architecture.md
```

### Design and planning docs

These are referenced opportunistically from other documents and are not required for first run.

- `docs/DASHBOARD_DESIGN_SPEC.md`
- `docs/FORGE_SPEC.md`
- `docs/OPERATOR_SPRINT_PLAN.md`

## Completeness list

Docs present under `docs/`:

- `api-reference.md`
- `architecture.md`
- `cli-reference.md`
- `configuration.md`
- `contributors.md`
- `deployment.md`
- `developers.md`
- `eas-integration.md`
- `getting-started.md`
- `learning-loop.md`
- `openclaw-integration.md`
- `security.md`
- `dependencies-code.md`
- `dependencies-docs.md`
- `DASHBOARD_DESIGN_SPEC.md`
- `FORGE_SPEC.md`
- `OPERATOR_SPRINT_PLAN.md`
