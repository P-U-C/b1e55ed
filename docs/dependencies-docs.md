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
  → docs/how-it-works.mdx
  → docs/getting-started.md
  → docs/mcp.md
  → docs/contributors.md
  → docs/architecture.md
  → docs/agent-interfaces.md
  → docs/oracle.md
  → docs/curator.md
  → docs/backtest.md
  → docs/authority-model.md
  → docs/eas-integration.md
  → docs/security.md
  → docs/deployment.md
  → docs/openclaw-integration.md
  → docs/learning-loop.md
  → ROADMAP.md
```

## Core docs

### `docs/how-it-works.mdx`

```text
how-it-works.mdx
  → getting-started.md
  → architecture.md
  → learning-loop.md
  → oracle.md
  → api/overview.mdx
  → producers/overview.mdx
```

### `docs/getting-started.md`

```text
getting-started.md
  → contributors.md
  → eas-integration.md
  → architecture.md
```

### `docs/mcp.md`

```text
mcp.md
  (no outgoing references to removed files — see api/ and producers/ sections)
```

### `docs/contributors.md`

```text
contributors.md
  → eas-integration.md
```

### `docs/architecture.md`

```text
architecture.md
  → authority-model.md
  → contributors.md
  → eas-integration.md
  → dependencies-code.md
  → producer-intelligence.md
```

### `docs/eas-integration.md`

```text
eas-integration.md
  → contributors.md
```

### `docs/security.md`

```text
security.md
  → crypto-primitives.md
  → deployment.md
```

### `docs/deployment.md`

```text
deployment.md
  → security.md
```

### `docs/dependencies-code.md`

```text
dependencies-code.md
  → architecture.md
```

**Referenced by:**
- architecture.md
- developers.md
- security.md

---

### `docs/dependencies-docs.md` (this file)

**References:**
- All docs (by definition)

**Referenced by:**
- README.md (via CI validation)

---

### `docs/internal/DASHBOARD_DESIGN_SPEC.md`

**References:**
```
internal/DASHBOARD_DESIGN_SPEC.md
  └→ architecture.md          (Referenced from Dashboard section)
```

**Referenced by:**
- architecture.md

---

### `docs/producer-intelligence.md`

**References:**
```
producer-intelligence.md
  (no outgoing references — self-contained specification)
```

**Referenced by:**
- docs/learning-loop.md
- docs/architecture.md

---

### `docs/learning-loop.md`

**References:**
```
learning-loop.md
  └→ ROADMAP.md               (Karma system design)
  └→ producer-intelligence.md  (P4 intelligence layer)
```

**Referenced by:**
- (Future: developers.md, ROADMAP.md)

---

## Sample Packs

### `samples/README.md`

**References:**
```
samples/README.md
  ├→ developers.md            (How to use templates)
  ├→ socials/README.md        (Social pack)
  ├→ tradfi/README.md         (TradFi pack)
  └→ onchain/README.md        (On-chain pack)
```

**Referenced by:**
- README.md
- developers.md

---

### `samples/socials/README.md`

**References:**
```
socials/README.md
  ├→ developers.md            (Producer guide)
  └→ ../README.md             (Pack overview)
```

**Referenced by:**
- samples/README.md
- developers.md

---

### `samples/tradfi/README.md`

**References:**
```
tradfi/README.md
  ├→ developers.md            (Producer guide)
  ├→ ../README.md             (Pack overview)
  └→ security.md              (API key storage)
```

**Referenced by:**
- samples/README.md
- developers.md

---

### `samples/onchain/README.md`

**References:**
```
onchain/README.md
  ├→ developers.md            (Producer guide)
  ├→ ../README.md             (Pack overview)
  └→ security.md              (API key storage)
```

**Referenced by:**
- samples/README.md
- developers.md

---

## Deployment Docs

### `DOCKER.md`

**References:**
```
DOCKER.md
  ├→ deployment.md            (Production setup)
  ├→ getting-started.md       (Quick start)
  └→ security.md              (Master password, TLS)
```

**Referenced by:**
- README.md
- deployment.md

---

## Roadmap

### `ROADMAP.md`

**References:**
```
ROADMAP.md
  ├→ architecture.md          (System components)
  ├→ developers.md            (Extension points to implement)
  └→ security.md              (Security gates)
```

**Referenced by:**
- README.md

---

## Full Dependency Hierarchy

```
Entry Points (no dependencies)
  ├─ README.md
  └─ (all docs are reachable from README)

Tier 1: Getting Started
  ├─ getting-started.md
  ├─ DOCKER.md
  └─ deployment.md

Tier 2: Architecture & Development
  ├─ architecture.md
  ├─ developers.md
  ├─ producer-intelligence.md
  ├─ dependencies-code.md
  └─ dependencies-docs.md (this file)

Tier 3: Operations
  ├─ deployment.md
  └─ security.md

Tier 4: Extensions
  ├─ samples/README.md
  ├─ samples/socials/README.md
  ├─ samples/tradfi/README.md
  └─ samples/onchain/README.md

Tier 5: Roadmap
  └─ ROADMAP.md
```

---

## Orphaned Documentation

**Definition:** Documents not referenced by any other doc.

**Check:**
```bash
# List all .md files
find docs samples -name "*.md" -type f > /tmp/all_docs.txt

# Grep for references in all docs
for doc in $(cat /tmp/all_docs.txt); do
  basename=$(basename "$doc")
  if ! grep -r "$basename" docs samples README.md DOCKER.md ROADMAP.md --include="*.md" | grep -v "^$doc:"; then
    echo "ORPHANED: $doc"
  fi
done
```

**Current orphans:** None (all docs reachable from README.md)

---

## Circular References

**Definition:** Doc A references B, B references C, C references A.

**Check:**
```bash
# Build reference graph and detect cycles
# (Manual review recommended)

# Example cycle detection:
docs/getting-started.md → docs/architecture.md
docs/deployment.md → docs/getting-started.md  # no cycle — one-way
```

**Current cycles:** None detected (all references are hierarchical)

---

## Broken Links

**Definition:** References to non-existent files.

**Check (CI validation):**
```bash
# Extract all [text](path.md) links
grep -o '\[.*\](docs/[^)]*\.md)' docs/*.md README.md DOCKER.md

# Verify file exists
for link in $links; do
  path=$(echo "$link" | sed 's/.*(\(.*\))/\1/')
  if [ ! -f "$path" ]; then
    echo "BROKEN: $link"
  fi
done
```

**Current broken links:** None (validated in Docs CI workflow)

---

## Documentation Coverage

**Required docs (all exist):**
- ✅ `README.md`
- ✅ `docs/getting-started.md`
- ✅ `docs/deployment.md`
- ✅ `docs/mcp.md`
- ✅ `docs/architecture.md`
- ✅ `docs/developers.md`
- ✅ `docs/security.md`
- ✅ `docs/dependencies-code.md`
- ✅ `docs/dependencies-docs.md`
- ✅ `DOCKER.md`
- ✅ `ROADMAP.md`
- ✅ `samples/README.md`
- ✅ `samples/socials/README.md`
- ✅ `samples/tradfi/README.md`
- ✅ `samples/onchain/README.md`

- ✅ `docs/openclaw-integration.md`

**Missing docs (future):**
- ⬜ `docs/troubleshooting.md` (common issues + fixes)
- ⬜ `docs/performance.md` (optimization guide)
- ⬜ `docs/changelog.md` (version history)
- ⬜ `CONTRIBUTING.md` (contribution guidelines)

---

## Maintaining This Graph

**When adding new docs:**
1. Add to appropriate tier in hierarchy
2. Document all references (A → B)
3. Update "Referenced by" sections in target docs
4. Run link checker (Docs CI workflow)
5. Commit changes to `dependencies-docs.md`

**When removing docs:**
1. Check "Referenced by" section
2. Update or remove references in those docs
3. Remove from hierarchy
4. Update dependency graph
5. Run link checker

---

## CI Validation

**Checks (`.github/workflows/docs.yml`):**
1. ✅ Brand vocabulary (no CT slang)
2. ✅ Internal link validation (no broken links)
3. ✅ Completeness check (all required docs exist)
4. ⬜ Dependency graph validation (future - see below)

**Future CI check:**
```bash
# Validate dependency graph is up to date
scripts/validate_doc_deps.sh

# Compares:
# - Actual links in docs (grep for [text](path.md))
# - Declared links in dependencies-docs.md
# - Fails if mismatch
```

---

### Additional Documentation

| Document | Purpose |
|----------|---------|
| [eas-integration.md](eas-integration.md) | Ethereum Attestation Service setup and usage |
| [internal/FORGE_SPEC.md](internal/FORGE_SPEC.md) | The Forge — identity derivation ritual spec |
| [identity.md](identity.md) | Identity key management, derivation, and recovery |
| [tutorial-agent-producer.md](tutorial-agent-producer.md) | Building an agent producer for b1e55ed |
| [agent-interfaces.md](agent-interfaces.md) | SSE, MCP, signal attribution, oracle |
| [oracle.md](oracle.md) | Producer provenance endpoint (public, no auth) |
| [curator.md](curator.md) | Curator pipeline — operator signal ingestion |
| [backtest.md](backtest.md) | Backtest engine — walk-forward, sweep, Kelly |
| [internal/EASTER_EGG_REFERENCE.md](internal/EASTER_EGG_REFERENCE.md) | Cultural reference library for codebase easter eggs |
| [internal/KARMA-SPEC.md](internal/KARMA-SPEC.md) | Karma score specification — inputs, update rule, calibration, failure modes |
| [internal/SEED_MANIFEST.md](internal/SEED_MANIFEST.md) | Reproducibility proof — cryptographic seed data manifest |

### Internal Documentation

These files are design references and sprint plans, not operator-facing guides.

| Document | Purpose |
|----------|---------|
| [internal/DASHBOARD_DESIGN_SPEC.md](internal/DASHBOARD_DESIGN_SPEC.md) | Dashboard design spec |
| [internal/OPERATOR_SPRINT_PLAN.md](internal/OPERATOR_SPRINT_PLAN.md) | Operator layer sprint plan (O1-O4) |
| [internal/MCP_SPRINT_PLAN.md](internal/MCP_SPRINT_PLAN.md) | MCP sprint implementation plan (S1-S5) |
| [internal/DEERFLOW_PLAN.md](internal/DEERFLOW_PLAN.md) | DeerFlow integration plan |
| [internal/FLYWHEEL_SPEC.md](internal/FLYWHEEL_SPEC.md) | Flywheel spec — attribution, karma, and signal loop |
| [internal/EASTER_EGG_REFERENCE.md](internal/EASTER_EGG_REFERENCE.md) | Cultural reference library for codebase easter eggs |
| [internal/KARMA-SPEC.md](internal/KARMA-SPEC.md) | Karma score specification |
| [internal/SEED_MANIFEST.md](internal/SEED_MANIFEST.md) | Reproducibility proof — cryptographic seed data manifest |
| [internal/FORGE_SPEC.md](internal/FORGE_SPEC.md) | The Forge — identity derivation ritual spec |
| [internal/b1e55ing-manifest.json](internal/b1e55ing-manifest.json) | b1e55ing manifest |

*Last updated: 2026-03-17*

---

## Mintlify site (docs/)

The Mintlify documentation site lives in `docs/` and is defined by `docs/docs.json`.
All pages below are registered in the nav and deployed to `docs.b1e55ed.permanentupperclass.com`.

### Getting Started

```text
docs/docs.json              ← nav/config (registers all nav pages)
docs/introduction.mdx       → quickstart.mdx, api/overview.mdx
docs/agents.mdx             → setup/agent-install.mdx
docs/quickstart.mdx         → setup/standalone-install.mdx, setup/agent-install.mdx, operations/cli-reference.mdx, how-it-works.mdx
docs/how-it-works.mdx       → getting-started.md, architecture.md, learning-loop.md, oracle.md, api/overview.mdx, producers/overview.mdx
docs/getting-started.md     → contributors.md, eas-integration.md, architecture.md
docs/llms.txt               (machine-readable LLM discovery index — not a navigable page)
```

### Setup

```text
docs/setup/standalone-install.mdx  → operator-standalone.md
docs/setup/agent-install.mdx       → operator-agent.md
docs/setup/oracle.mdx              → oracle.md
docs/setup/telegram.mdx
docs/setup/tailscale.mdx
docs/deployment.md                 → security.md
docs/operator-standalone.md        → getting-started.md
docs/operator-agent.md             → operator-standalone.md, openclaw-integration.md
```

### Operations

```text
docs/operations/cli-reference.mdx   (canonical CLI reference — authoritative)
docs/operations/config-reference.mdx (canonical config reference — authoritative)
docs/operations/daily.mdx
docs/operations/troubleshooting.mdx
docs/signal-benchmarking-ops-guide.md (standalone — oracle builders, signal evaluation)
docs/identity.md                    (standalone — key hierarchy and recovery)
docs/authority-model.md             (standalone — single-writer event store rules)
docs/security.md                    → crypto-primitives.md, deployment.md
```

### Features

```text
docs/curator.md        (standalone — operator signal ingestion pipeline)
docs/learning-loop.md  → ROADMAP.md, producer-intelligence.md
docs/backtest.md       (standalone — walk-forward, Kelly, regime-conditioned results)
```

### Integrations

```text
docs/deerflow.md       (standalone — DeerFlow research agent integration)
docs/mcp.md            (standalone — MCP integration reference)
docs/agent-interfaces.md (standalone — SSE, MCP, signal attribution)
docs/eas-integration.md  → contributors.md
docs/openclaw-integration.md (standalone — OpenClaw operator layer)
```

### API

```text
docs/api/overview.mdx       (standalone — API overview)
docs/api/signals.mdx        (standalone — signals API)
docs/api/contributors.mdx   → contributors.md
docs/api/brain.mdx          (standalone — brain API)
docs/api/positions.mdx      (standalone — positions API)
docs/api/karma.mdx          → internal/KARMA-SPEC.md
```

### Producers

```text
docs/producers/overview.mdx          (canonical — producers overview)
docs/producers/symbol-packs.mdx
docs/producers/tuning-guide.mdx
docs/producers/external-producers.mdx → docs/producers/spi-interface.mdx, docs/producers/spi-adapter.mdx
docs/producers/spi-interface.mdx     (standalone — formal SPI protocol contract)
docs/producers/spi-adapter.mdx       → docs/producers/external-producers.mdx
docs/producers/reference.mdx         → all producers/* pages, tutorial-agent-producer.md, producer-intelligence.md
```

### Contributing

```text
docs/contributing/contributor-registration.mdx → contributors.md
docs/contributing/karma-attribution.mdx        → internal/KARMA-SPEC.md
docs/contributing/how-to-contribute.mdx
docs/developers.md  (standalone — extending and contributing)
docs/contributors.md → eas-integration.md
```

### Reference

```text
docs/architecture.md   → authority-model.md, contributors.md, eas-integration.md, producer-intelligence.md
docs/crypto-primitives.md (standalone — hash functions, key generation, chain verification)
docs/whitepaper-technical.md (standalone)
docs/whitepaper-summary.md (standalone)
docs/whitepaper-onepager.md (standalone)
```

## Operator guides (docs/)

```text
docs/operator-standalone.md → getting-started.md
docs/operator-agent.md      → operator-standalone.md, openclaw-integration.md
```

## CLI setup command modules

```text
engine/cli/main.py             ⇒ engine/cli/commands/setup.py
engine/cli/commands/setup.py   → engine/cli/main.py (_cmd_setup), scripts/setup-connected.sh
```

## MCP integration layer

### `engine/mcp/__init__.py`

```text
engine/mcp/__init__.py
  → engine/mcp/registry.py
  → engine/mcp/server.py
  → engine/mcp/types.py
```

### `engine/mcp/types.py`

```text
engine/mcp/types.py
  (no internal deps — standalone type definitions)
```

### `engine/mcp/registry.py`

```text
engine/mcp/registry.py
  → engine/mcp/types.py
```

### `engine/mcp/server.py`

```text
engine/mcp/server.py
  → engine/mcp/registry.py
  → dataclasses.asdict
  (optional) mcp SDK import (FastMCP SSE transport)
```

### `engine/mcp/auth.py`

```text
engine/mcp/auth.py
  → hmac.compare_digest
  → fastapi (Header, HTTPException)
```

### `engine/mcp/client.py`

```text
engine/mcp/client.py
  (optional) mcp SDK import
  → httpx (HTTP transport)
```

### `api/routes/mcp.py`

```text
api/routes/mcp.py
  → api/deps.py (get_config, get_db)
  → engine/mcp/auth.py
  → engine/mcp/registry.py
  → engine/core/database.py
```

### `engine/producers/financial_datasets.py`

```text
engine/producers/financial_datasets.py
  → engine/mcp/client.py
  → engine/producers/base.py
  → engine/producers/registry.py
  → engine/core/events.py
  → engine/core/models.py
```

### `engine/producers/polymarket.py`

```text
engine/producers/polymarket.py
  → engine/producers/base.py
  → engine/producers/registry.py
  → engine/core/events.py
  → engine/core/models.py
  → httpx (Gamma + CLOB API calls)
```

## Flywheel

```text
docs/internal/FLYWHEEL_SPEC.md → docs/architecture.md, CHANGELOG.md
```

## Interpreter seam

### `engine/core/interpreter.py`

```text
engine/core/interpreter.py
  → engine/core/events.py (ForecastPayload, AbstentionReason)
  → engine/core/forecast.py (abstain)
```

## Whitepapers

```text
docs/whitepaper-technical.md (standalone — no internal deps)
docs/whitepaper-summary.md (standalone — no internal deps)
docs/whitepaper-onepager.md (standalone — no internal deps)
```

## DeerFlow Research Trigger

```text
engine/producers/deerflow_research_trigger.py
  → engine/core/events.py (ResearchSignalPayload, SignalClass)
  → engine/core/database.py (Database)
  → engine/producers/deerflow_research.py (DeerflowResearchProducer)
  → engine/artifacts/store.py (ArtifactStore)
```

## DeerFlow Integration Plan

```text
docs/internal/DEERFLOW_PLAN.md (standalone — integration plan, no internal deps)
```

## DeerFlow Operator Guide

```text
docs/deerflow.md (standalone — setup, tool reference, troubleshooting)
  → gateway/README.md
  → integrations/deerflow/extensions_config.json
```

## Signal Benchmarking Operations Guide

```text
docs/signal-benchmarking-ops-guide.md (standalone — operational guide for oracle builders)
```

## SPI External Producer Guide

```text
docs/producers/external-producers.mdx
  depends on: docs/producers/spi-interface.mdx, docs/producers/spi-adapter.mdx
```

## SPI Interface Specification

```text
docs/producers/spi-interface.mdx (standalone — formal SPI protocol contract)
```

## SPI Adapter Spec

```text
docs/producers/spi-adapter.mdx
  → docs/producers/external-producers.mdx  (back-reference for native mode)
```

## Tutorial: Agent Producer

```text
docs/tutorial-agent-producer.md (standalone — step-by-step guide to building a custom agent producer)
```

**Referenced by:**
- docs/producers/reference.mdx

## Producer Intelligence

```text
docs/producer-intelligence.md (standalone — intelligence layer, signal synthesis)
```

**Referenced by:**
- docs/producers/reference.mdx
- docs/architecture.md
- docs/learning-loop.md
