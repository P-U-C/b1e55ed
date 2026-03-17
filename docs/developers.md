---
title: "Developer Guide"
description: "How to extend, contribute to, and build on b1e55ed."
---

# Developer Guide

How to extend and contribute to b1e55ed.

---

## Project Structure

```
b1e55ed/
├── api/                    # FastAPI app and routes
│   ├── main.py             # App factory, router mounts
│   ├── auth.py             # Bearer token auth
│   ├── deps.py             # FastAPI dependencies
│   └── routes/             # Route modules by domain
├── engine/                 # Core engine
│   ├── brain/              # Brain orchestration
│   ├── core/               # DB, config, events, webhooks
│   ├── integrations/       # EAS, forge, oracle
│   ├── producers/          # Signal producers
│   └── strategies/         # Backtest strategies
├── dashboard/              # Starlette dashboard
├── docs/                   # Documentation
├── tests/                  # Test suite
│   ├── unit/               # Fast, isolated tests
│   └── integration/        # End-to-end tests
├── config/                 # Config files
│   ├── default.yaml        # Repo defaults
│   └── user.yaml           # Operator overlay (gitignored)
└── scripts/                # Utilities and validation
```

## Key Modules

| Module | Purpose |
|--------|---------|
| `engine/core/db.py` | SQLite event store, hash chain |
| `engine/core/config.py` | Config model, env var mapping |
| `engine/core/contributors.py` | Contributor registry, scoring |
| `engine/core/scoring.py` | Attribution scoring logic |
| `engine/core/webhooks.py` | Webhook dispatch |
| `engine/brain/orchestrator.py` | Brain cycle orchestration |
| `engine/brain/synthesis.py` | Multi-domain conviction synthesis |
| `engine/brain/regime.py` | Regime detection |
| `engine/integrations/oracle.py` | Oracle provenance projection |
| `engine/integrations/eas.py` | EAS attestation client |
| `engine/integrations/forge.py` | Identity derivation |
| `api/routes/signals.py` | Signal submit, attribution |
| `api/routes/mcp.py` | MCP JSON-RPC server |
| `api/routes/oracle.py` | Oracle endpoint |
| `api/routes/events.py` | SSE event stream |

---

## Test Setup

```bash
uv run pytest --ignore=tests/unit/test_eas_client.py -x -q
```

The EAS client test is excluded by default — it requires external network access.

For a specific test file:

```bash
uv run pytest tests/unit/test_brain.py -v
```

---

## Adding a Producer

Producers live in `engine/producers/`. They emit signal events to the event store.

### 1. Create the producer module

```python
# engine/producers/your_producer.py

from engine.core.db import EventStore
from engine.core.events import emit_event

class YourProducer:
    """Generates signals from [your source]."""

    name = "your_producer"
    domain = "technical"  # or: onchain, social, tradfi, curator

    def __init__(self, config: dict):
        self.config = config

    def run(self, db: EventStore) -> list[str]:
        """Run one cycle. Return list of emitted event IDs."""
        event_ids = []

        # Fetch data, compute signal
        direction = "bullish"  # or: bearish, neutral
        conviction = 7.0

        event_id = emit_event(
            db=db,
            event_type=f"signal.{self.domain}.your_signal.v1",
            source=f"producer.{self.name}",
            payload={
                "symbol": "BTC",
                "direction": direction,
                "conviction": conviction,
                "rationale": "...",
            },
        )
        event_ids.append(event_id)
        return event_ids
```

### 2. Register via CLI

```bash
b1e55ed producers register \
  --name your_producer \
  --domain technical \
  --endpoint http://localhost:8001/poll \
  --schedule "*/15 * * * *"
```

Or via config in `config/user.yaml` for built-in producers.

### 3. Write tests

```python
# tests/unit/test_your_producer.py

def test_your_producer_emits_signal(tmp_db):
    producer = YourProducer(config={})
    event_ids = producer.run(tmp_db)
    assert len(event_ids) > 0
```

---

## Adding a Strategy

Strategies live in `engine/strategies/`. They consume signals and produce trade intents for the backtest engine.

```python
# engine/strategies/your_strategy.py

from engine.strategies.base import BaseStrategy

class YourStrategy(BaseStrategy):
    """Multi-factor strategy combining [signals]."""

    name = "your_strategy"

    def evaluate(self, signals: list[dict]) -> list[dict]:
        """Return list of trade intents."""
        intents = []
        # Group by symbol, check consensus, size via Kelly
        return intents
```

Register in the strategy registry used by the backtest CLI.

---

## Extension Registry Pattern

The engine uses a registry pattern for producers and strategies. Built-in components are discovered at import time. External components register via the database or config overlay.

For producers: `engine/core/producers.py` — `ProducerRegistry`
For strategies: `engine/strategies/__init__.py` — `StrategyRegistry`

---

## Contribution Guidelines

1. **Branch from `develop`** — all PRs target `develop`, not `main`
2. **Tests required** — new code without tests won't merge
3. **No broken links** — run `bash scripts/validate_doc_deps.sh` before commit
4. **Lint clean** — `uv run ruff check . && uv run ruff format --check .`
5. **Type-check** — `uv run mypy engine/ api/` for changed modules

## CI Requirements

Every PR must pass:

```bash
uv run pytest --ignore=tests/unit/test_eas_client.py -x -q   # tests
uv run ruff check .                                            # lint
uv run ruff format --check .                                   # format
bash scripts/validate_doc_deps.sh                              # doc deps
```

Type checking runs on CI for the `engine/` and `api/` packages.

---

## See Also

- [Architecture](architecture.md) — how the pieces fit together
- [API reference](api/overview.mdx) — all endpoints
- [CLI reference](operations/cli-reference.mdx) — all commands
- [Configuration](operations/config-reference.mdx) — all config keys
