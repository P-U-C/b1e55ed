# Code Dependency Graph

Module-level dependencies for b1e55ed codebase.

---

## Notation

```
A → B     "A imports B"
A ⇒ B     "A depends heavily on B (multiple imports or core functionality)"
```

---

## Core Layer

### `engine/core/`

**Foundation modules** (no internal dependencies):
```
events.py          (EventType enum, canonical_json)
types.py           (ProducerHealth, ProducerResult, etc.)
```

**Models** (depends on events):
```
models.py          → events
  ├─ Event dataclass
  └─ compute_event_hash()
```

**Database** (depends on models + events):
```
database.py        ⇒ models, events
  ├─ Database class (SQLite event store)
  ├─ append_event()
  └─ verify_hash_chain()
```

**Configuration** (minimal dependencies):
```
config.py          → types
  ├─ Config (Pydantic BaseSettings)
  └─ load from YAML
```

**Client** (data fetching):
```
client.py          → config
  └─ DataClient (price/volume/features)
```

**Projections** (depends on events + types):
```
projections.py     → events, types
  ├─ SignalsLatestProjector
  ├─ RegimeStateProjector
  ├─ PositionStateProjector
  └─ ProjectionManager
```

**Metrics** (standalone):
```
metrics.py         (MetricsRegistry, counters, gauges)
```

**Dependency order (build/test):**
```
events, types
  ↓
models, config, metrics
  ↓
database, client
  ↓
projections
```

---

## Security Layer

### `engine/security/`

```
identity.py        (NodeIdentity, Ed25519 signing)
keystore.py        → identity (Fernet vault)
audit.py           → database, identity (AuditLogger)
redaction.py       (sanitize_for_log, redact_secrets)
```

**Dependency order:**
```
identity (standalone)
  ↓
keystore, redaction
  ↓
audit
```

---

## Producers Layer

### `engine/producers/`

```
base.py            ⇒ core/database, core/client, core/config
  ├─ ProducerContext
  ├─ ProducerBase
  └─ draft_event()

events.py          (producer-specific EventType extensions)

registry.py        → base (producer discovery + loading)

individual producers/
  rsi.py           → base, client
  momentum.py      → base, client
  social.py        → base, client
  whale.py         → base, client
  funding.py       → base, client
```

**Dependency chain:**
```
core/* (database, client, config, types)
  ↓
producers/base
  ↓
producers/registry, producers/{rsi,momentum,...}
```

---

## Strategies Layer

### `engine/strategies/`

```
base.py            → core/types (Strategy protocol)

individual strategies/
  confluence.py    → base
  momentum.py      → base
  ma_crossover.py  → base
  combined.py      → base
```

**Dependency chain:**
```
core/types
  ↓
strategies/base
  ↓
strategies/{confluence,momentum,...}
```

---

## Brain Layer

### `engine/brain/`

```
kill_switch.py     → core/database, core/config
orchestrator.py    ⇒ core/database, core/config, security/identity
                   → producers/registry, strategies/*
pcs_enricher.py    → core/client, core/types
feature_store.py   → core/database
synthesizer.py     (future - not yet implemented)
```

**Dependency chain:**
```
core/* + security/identity
  ↓
producers/*, strategies/*
  ↓
kill_switch, pcs_enricher, feature_store
  ↓
orchestrator (assembles everything)
```

---

## Execution Layer

### `engine/execution/`

```
oms.py             → core/database, core/config
                   → security/identity
policy.py          → core/config (position limits, leverage)
karma.py           → core/database, security/identity
```

**Dependency chain:**
```
core/* + security/identity
  ↓
policy, oms, karma
```

---

## API Layer

### `api/`

```
main.py            → routes/*, core/config
routes/__init__.py → routes/{health,signals,brain,...}
routes/brain.py    → core/database, brain/orchestrator
                   → security/identity, deps, auth
routes/signals.py  → core/database, deps, auth
routes/positions.py→ core/database, execution/oms, deps, auth
deps.py            → core/config, core/database
                   → security/identity
auth.py            → core/config, deps
```

**Dependency chain:**
```
core/* + security/* + brain/* + execution/*
  ↓
api/deps, api/auth
  ↓
api/routes/*
  ↓
api/main
```

---

## Dashboard Layer

### `dashboard/`

```
app.py             → core/database, core/config
                   → api/deps (reuses FastAPI deps)
```

**Dependency chain:**
```
core/* + api/deps
  ↓
dashboard/app
```

---

## CLI Layer

### `engine/cli.py`

```
cli.py             ⇒ core/*, security/*, brain/*, execution/*
  ├─ setup command
  ├─ brain command → brain/orchestrator
  ├─ api command → api/main
  └─ dashboard command → dashboard/app
```

**Dependency chain:**
```
ALL layers
  ↓
cli (entry point)
```

---

## Full Dependency Hierarchy

```
Layer 0: Foundation
  └─ events, types, metrics

Layer 1: Core Infrastructure
  └─ models, config, client, database, projections

Layer 2: Security
  └─ identity, keystore, audit, redaction

Layer 3: Domain Logic
  ├─ producers (base + registry + implementations)
  └─ strategies (base + implementations)

Layer 4: Orchestration
  └─ brain (orchestrator, kill_switch, pcs_enricher, feature_store)

Layer 5: Execution
  └─ execution (oms, policy, karma)

Layer 6: Interfaces
  ├─ api (routes, auth, deps, main)
  ├─ dashboard (app)
  └─ cli (commands)
```

---

## Import Rules

**Allowed:**
- Lower layer → Lower layer (same level or below)
- Higher layer → Lower layer

**Forbidden:**
- Lower layer → Higher layer (creates circular dependency)
- Horizontal imports within same component (use __init__.py)

**Examples:**

✅ **Good:**
```python
# brain/orchestrator.py
from engine.core.database import Database  # Layer 4 → Layer 1
from engine.producers.registry import get_producers  # Layer 4 → Layer 3
```

❌ **Bad:**
```python
# core/database.py
from engine.brain.orchestrator import BrainOrchestrator  # Layer 1 → Layer 4 (CIRCULAR)
```

---

## Circular Dependency Detection

**Check for cycles:**
```bash
# Using pydeps (install: pip install pydeps)
pydeps engine --max-bacon 2 --cluster

# Or manually:
python -c "
import sys
from importlib import import_module

def check_imports(module_name, visited=None):
    if visited is None:
        visited = set()
    if module_name in visited:
        print(f'CYCLE: {module_name}')
        return
    visited.add(module_name)
    # ... (simplified, real implementation uses ast)
"
```

---

## Testing Dependencies

**Unit tests:**
- Mock dependencies from higher layers
- Only test module in isolation

**Integration tests:**
- Allow cross-layer dependencies
- Test full flows (e.g., producer → database)

**Example:**
```python
# tests/unit/test_database.py
# ✅ No imports from brain/, execution/, api/

# tests/integration/test_producer_contract.py
# ✅ Imports producers/base, core/database (contract test)
```

---

## Adding New Modules

**Checklist:**
1. Identify which layer it belongs to
2. Only import from same or lower layers
3. Update this dependency graph
4. Add to CI dependency validation (when implemented)
5. Run `pydeps` to verify no cycles introduced

---

*Auto-generated dependency graph: Run `scripts/generate_dep_graph.sh` (when implemented)*

*Last updated: 2026-02-19*
