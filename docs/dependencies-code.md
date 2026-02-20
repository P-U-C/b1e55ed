# Code Dependency Graph

Module-level dependencies for b1e55ed.

Notation:

```text
A → B     A imports B
A ⇒ B     A depends heavily on B
```

## Foundation

```text
engine/core/events.py
engine/core/types.py
engine/core/metrics.py
```

## Core

```text
engine/core/models.py        → engine/core/events.py
engine/core/database.py      ⇒ engine/core/models.py, engine/core/events.py
engine/core/config.py        → (pydantic, yaml)
engine/core/client.py        → engine/core/config.py
engine/core/projections.py   → engine/core/events.py, engine/core/types.py
```

## Contributor layer (C1)

```text
engine/core/contributors.py  ⇒ engine/core/database.py
engine/core/scoring.py       ⇒ engine/core/database.py
api/routes/contributors.py   ⇒ engine/core/contributors.py, engine/core/scoring.py, api/errors.py
```

## Integrations

```text
engine/integrations/forge.py (standalone grinder; used by CLI identity forge)
engine/integrations/eas.py   → engine/integrations/eas_schema.py
```

## Webhooks

```text
engine/core/webhooks.py      → engine/core/models.py
```

## API

```text
api/errors.py                (structured error format)
api/routes/__init__.py       → api/routes/*
api/main.py                  ⇒ api/routes/__init__.py, engine/core/config.py
```

## CLI

```text
engine/cli.py                ⇒ (imports across layers; lazy-import by design)
```
