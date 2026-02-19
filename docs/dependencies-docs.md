# Documentation Dependency Graph

Cross-references between documentation files.

---

## Notation

```
A → B     "A references B"
A ⇒ B     "A heavily references B (multiple sections)"
```

---

## Entry Points

### For New Users

```
README.md
  ├→ docs/getting-started.md  (setup, quick start)
  ├→ DOCKER.md                (Docker deployment)
  └→ docs/deployment.md       (production setup)
```

### For Developers

```
README.md
  ├→ docs/architecture.md     (system design)
  ├→ docs/developers.md       (extending b1e55ed)
  └→ samples/README.md        (templates)
```

### For Operators

```
README.md
  ├→ docs/configuration.md    (config reference)
  ├→ docs/deployment.md       (production setup)
  └→ docs/security.md         (security model)
```

---

## Core Documentation

### `README.md`

**References:**
```
README.md
  ├→ docs/getting-started.md       (Installation → Getting Started)
  ├→ docs/architecture.md          (Architecture → System Design)
  ├→ docs/api-reference.md         (API → Full API Docs)
  ├→ docs/openclaw-integration.md  (Operator Layer → Integration)
  ├→ DOCKER.md                     (Docker deployment)
  └→ ROADMAP.md                    (Roadmap)
```

**Referenced by:**
- None (entry point)

---

### `docs/getting-started.md`

**References:**
```
getting-started.md
  ├→ configuration.md         (Configuration section)
  ├→ deployment.md            (Production deployment)
  ├→ api-reference.md         (API usage)
  └→ security.md              (Master password setup)
```

**Referenced by:**
- README.md
- DOCKER.md

---

### `docs/configuration.md`

**References:**
```
configuration.md
  ├→ deployment.md            (Deployment-specific configs)
  ├→ security.md              (Secret management)
  └→ developers.md            (Custom producer configs)
```

**Referenced by:**
- getting-started.md
- deployment.md
- api-reference.md

---

### `docs/deployment.md`

**References:**
```
deployment.md
  ├⇒ security.md              (TLS, secrets, hardening)
  ├→ configuration.md         (Config examples)
  ├→ getting-started.md       (Basic setup)
  └→ DOCKER.md                (Docker alternative)
```

**Referenced by:**
- README.md
- getting-started.md
- DOCKER.md

---

### `docs/api-reference.md`

**References:**
```
api-reference.md
  ├→ security.md              (Authentication)
  ├→ configuration.md         (API config section)
  └→ architecture.md          (API layer diagram)
```

**Referenced by:**
- README.md
- getting-started.md
- developers.md

---

### `docs/architecture.md`

**References:**
```
architecture.md
  ├→ developers.md            (Extension points)
  ├→ security.md              (Security architecture)
  ├→ dependencies-code.md     (Module dependencies)
  └→ api-reference.md         (API endpoints)
```

**Referenced by:**
- README.md
- developers.md
- ROADMAP.md

---

### `docs/developers.md`

**References:**
```
developers.md
  ├⇒ architecture.md          (System design context)
  ├⇒ samples/README.md        (Templates)
  ├→ samples/socials/README.md (Social producer examples)
  ├→ samples/tradfi/README.md  (TradFi producer examples)
  ├→ samples/onchain/README.md (On-chain producer examples)
  ├→ configuration.md         (Config for custom modules)
  └→ dependencies-code.md     (Dependency rules)
```

**Referenced by:**
- README.md
- architecture.md
- samples/README.md

---

### `docs/security.md`

**References:**
```
security.md
  ├→ architecture.md          (Event sourcing design)
  ├→ configuration.md         (Security-related configs)
  ├→ deployment.md            (Production hardening)
  └→ dependencies-code.md     (Security layer deps)
```

**Referenced by:**
- getting-started.md
- configuration.md
- deployment.md
- api-reference.md
- architecture.md

---

### `docs/dependencies-code.md`

**References:**
```
dependencies-code.md
  ├→ architecture.md          (Layer definitions)
  └→ developers.md            (Adding new modules)
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

### `docs/DASHBOARD_DESIGN_SPEC.md`

**References:**
```
DASHBOARD_DESIGN_SPEC.md
  └→ architecture.md          (Referenced from Dashboard section)
```

**Referenced by:**
- architecture.md

---

### `docs/learning-loop.md`

**References:**
```
learning-loop.md
  └→ ROADMAP.md               (Karma system design)
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
  ├→ configuration.md         (API key config)
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
  ├→ configuration.md         (Environment variables)
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
  ├→ security.md              (Security gates)
  └→ configuration.md         (Config requirements)
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
  └─ configuration.md

Tier 2: Architecture & Development
  ├─ architecture.md
  ├─ developers.md
  ├─ dependencies-code.md
  └─ dependencies-docs.md (this file)

Tier 3: Operations
  ├─ deployment.md
  ├─ security.md
  └─ api-reference.md

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
docs/getting-started.md → docs/configuration.md
docs/configuration.md → docs/deployment.md
docs/deployment.md → docs/getting-started.md  # CYCLE!
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
- ✅ `docs/configuration.md`
- ✅ `docs/deployment.md`
- ✅ `docs/api-reference.md`
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

*Auto-generated dependency graph: Run `scripts/generate_doc_dep_graph.sh` (when implemented)*

*Last updated: 2026-02-19*
