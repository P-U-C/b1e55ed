# Changelog

## v1.0.0-beta.3 — 2026-02-25

226 commits. 583 tests. Full CI green across Python 3.11 + 3.12.

---

### Security

**API rate limiting (SEC1)**
- Per-IP rate limiting middleware on all API endpoints
- Configurable limits per route class (read vs write vs admin)

**Kill switch auth isolation (SEC1b)**
- Separate auth token for kill switch endpoints
- Kill switch operations cannot be performed with the standard API token
- Prevents a compromised API token from disabling safety mechanisms

**Crypto primitive unification (C1)**
- Migrated to Argon2id for identity file key derivation (from PBKDF2; keystore still uses PBKDF2+Fernet)
- AES-256-GCM for all symmetric encryption at rest
- Single `engine/security/` module handles all crypto — no scattered implementations

**Unified identity (U1)**
- Forge Ethereum key (secp256k1) now derives the Ed25519 signing key
- Single master identity instead of two independent keypairs
- One `B1E55ED_MASTER_PASSWORD` controls everything

**Safety hotfix (FIX1)**
- 6 critical fixes from security review: input sanitization, hash comparison timing, key export guard, session isolation, error message redaction, config validation strictness

---

### Permissions + Governance

**Role-based permissions (P1)**
- Contributor roles (`operator`, `agent`, `tester`, `curator`) enforce operation scope
- Permission checks on signal submission, producer registration, config writes
- Role constraints configurable per deployment

**Authority model (A1)**
- Single-writer enforcement via application-level write lock
- `b1e55ed integrity` detects concurrent writer violations
- Write-lock tests validate chain integrity across concurrent scenarios
- Documented in `docs/authority-model.md`

**Karma settlement governance (K1)**
- Multi-step settlement workflow: intent → review → settlement → receipt
- Governance controls: threshold, cooldown, approval gates
- Settlement history queryable via `GET /karma/receipts`

---

### Producer Infrastructure

**Producer hardening (PH1)**
- Response size caps on all producer outputs (prevent memory exhaustion)
- JSON schema guard — malformed producer payloads rejected before entering event store
- Configurable per-producer response limits

**Producer quarantine (PH1b)**
- Producers quarantined after N consecutive failures (configurable)
- Quarantined producers skipped during brain cycles
- Auto-recovery after cooldown period
- Status visible via `GET /producers/status`

---

### Signal Quality

**Calibrated scoring — anti-gaming (S1)**
- Contributor scores designed to resist gaming
- Rolling window, streak normalization, outlier dampening
- Score history preserved for audit

**Signal anti-spam (S2)**
- Per-contributor signal rate limiting
- Burst protection with configurable window
- Duplicate signal detection and deduplication

**Signal normalization (SQ1)**
- Asset-aware on-chain signal normalization wired into conviction scoring
- Whale signal threshold: 0.1% of market cap = full signal
- Exchange flow threshold: 0.5% of daily volume = full signal
- Normalization prevents large-cap bias in multi-asset synthesis

---

### Data Infrastructure

**Social intelligence pipeline**
- Collectors: Farcaster, Reddit, TikTok, Google Trends, Fear & Greed Index, Polymarket
- Extractors: entity recognition, LLM-assisted signal analysis
- Filters: echo chamber detection, preprocessing
- Scoring: aggregator, contrarian signals, divergence detection, influencer weighting, temporal decay
- Full pipeline: `engine/social/pipeline.py`

**TradFi data integration**
- FRED: macro rates, spreads, yield curve data
- Yahoo Finance: equity OHLCV, earnings, fundamentals
- SEC EDGAR: insider filings (Form 4, 13F, 8-K)
- OpenInsider: insider trade aggregation and cluster detection

**Feature store**
- Frozen feature snapshots per brain cycle
- Data quality monitoring with schema validation
- Prevents silent schema mismatches from corrupting conviction scores
- `engine/brain/feature_store.py`, `engine/brain/data_quality.py`

---

### Backtest Engine (B1a–B1h)

Complete walk-forward backtesting system with FDR-corrected validation.

**Strategies (10)**
- Momentum, MA crossover, RSI reversion, mean reversion, trend following
- Breakout, volatility, funding arbitrage
- Combined (multi-factor) — best empirical results

**CLI commands**
- `b1e55ed backtest walkforward` — walk-forward with OOS splits
- `b1e55ed backtest gridsweep` — parameter grid sweep, FDR across all combos
- `b1e55ed backtest megasweep` — all strategies × all params × all assets in parallel
- `b1e55ed backtest regime` — per-regime performance breakdown with FDR
- `b1e55ed kelly` — dynamic Kelly criterion from realized trade history

**Validation**
- FDR correction (Benjamini-Hochberg) mandatory on all multi-combo sweeps
- Walk-forward OOS splits prevent lookahead
- 96K+ parameter combinations tested in mega sweep
- Key finding: combined multi-factor strategies (momentum + MA crossover) survive strict FDR at q=0.05; single-factor strategies do not

---

### Agent Interfaces (AG1)

**SSE event stream**
- `GET /api/v1/events/stream` — real-time Server-Sent Events feed
- Domain filtering: `?domain=alert`, `?domain=signal`
- Resume support: `?since=<event_id>`

**MCP server**
- `POST /api/v1/mcp` — JSON-RPC 2.0 compliant
- 6 tools: `get_brain_status`, `get_recent_signals`, `get_open_positions`, `get_signal_attribution`, `emit_producer_signal`, `b1e55ed_provenance_check`

**Signal attribution**
- `GET /api/v1/signals/{id}/attribution` — contributor, source, outcome if settled

**Producer feedback**
- `POST /api/v1/producers/{id}/feedback` — agents report signal outcomes to the learning loop

**Capability discovery**
- `GET /api/v1/capabilities` — tools, event domains, producer list; designed for agent onboarding

**Trace sessions**
- `POST /api/v1/trace/sessions` — create stateful agent session
- `GET /api/v1/trace/sessions/{id}` — session state
- `DELETE /api/v1/trace/sessions/{id}` — close session

---

### External Auditability (E1)

**New CLI commands**
- `b1e55ed anchor [--eas]` — print current hash-chain root; optionally anchor to EAS
- `b1e55ed export karma [--format jsonl|json|csv] [--include-chain] [--from DATE] [--to DATE]` — export karma attribution data for seed dataset and analysis
- `b1e55ed replay` — rebuild all projections from event log
- `b1e55ed integrity` — verify hash chain integrity end-to-end

**GitHub auto-publish**
- On contributor registration, opens a GitHub issue in a designated repo
- Creates a public record without requiring on-chain transactions
- Configure: `github_publish.token`, `github_publish.owner`, `github_publish.repo`
- Publishing fires whenever a token is present — no separate enable flag
- `GET /contributors/{id}/attestation` includes `published` field

---

### Oracle Provenance Layer (OR1)

**Public provenance endpoint**
- `GET /api/v1/oracle/producers/{id}/provenance` — no authentication required
- Returns: chain verification status, total signals, P&L attribution, operator coverage, 7d/30d/90d attribution windows with hit rates and max drawdown
- Anti-Goodhart response header on every response: `X-Attribution-Notice`
- "Unknown producer" response for unregistered sources — agents can proceed without blocking

**MCP tool**
- `b1e55ed_provenance_check` — agents check producer lineage before acting on a signal
- Available via `POST /api/v1/mcp` with `tools/call`

**Query logging**
- Every oracle query logged to `data/oracle_queries.jsonl` in anonymized form
- Producer IDs hashed (sha256[:8]) — never logged raw
- Demand intelligence only — never feeds back into karma scores

**Specifications**
- `docs/KARMA-SPEC.md` — karma score inputs, update rule (exponential moving average), calibration bands, failure modes, 30-second explainability test
- `docs/SEED_MANIFEST.md` — reproducibility proof stub; cryptographic verification structure for initial karma scores

---

### CLI Decomposition (AG2)

- CLI refactored from `engine/cli.py` (single 1800+ line file) into `engine/cli/` package
- Individual command modules: `anchor.py`, `export.py`, per-command files
- Full backward compatibility via re-exports — no operator changes required

---

### Easter Egg Hook

- `scripts/b1e55ing.py` — auto-injects cultural references as a commit on every PR
- 3-path architecture: agent primary (this system, via heartbeat) → Gemini Flash fallback → post-merge catch-all
- GitHub Actions workflow sends direct Telegram signal to agent on PR open — no polling
- Log2-tiered scaling: 1 file→1 blessing, 51+ files→6 blessings (hard cap)
- Git author: `a b1e55ing` — the name is the egg
- 27 tests

---

### Documentation

**Complete sweep**
- 15 operator-facing guides covering every feature
- New: `docs/oracle.md`, `docs/agent-interfaces.md`, `docs/curator.md`, `docs/backtest.md`
- `docs/internal/` — design specs and sprint plans removed from public navigation
- All docs verified for accuracy against current codebase

**Code dependency graph**
- 174 modules mapped across 7 layers (primitives → core → security → producers → brain → execution → interfaces)
- Layer violation detection in CI via `scripts/validate_code_deps.py`
- Fixed: lazy imports inside methods no longer trigger false-positive layer violations

**CI auto-update**
- `dep-graphs.yml` — fires on every push to main/develop when Python or doc files change
- Auto-detects undocumented modules, appends to `## Undocumented (auto-detected)` section
- Auto-detects new docs, adds to `dependencies-docs.md`
- Commits with `[skip ci]` if anything changed — no manual maintenance required

---

### Tests

| Suite | Count |
|-------|-------|
| Unit | ~480 |
| Integration | ~50 |
| **Total** | **530** |

CI matrix: Python 3.11 + 3.12. Jobs: tests, lint, typecheck, build, security scan, smoke, shellcheck, brand vocabulary, doc completeness, internal links, code deps, doc deps, compose.

---

## v1.0.0-beta.2 — 2026-02-19

- Operator layer (OpenClaw integration spec)
- Karma treasury and settlement
- EAS off-chain attestations
- Kill switch multi-level gating (L0–L4)
- Regime detection and conviction scoring
- Paper trading mode
- Contributor registry and scoring

## v1.0.0-beta.1 — 2026-02-10

- Initial release
- Append-only event store with hash chain
- Brain synthesis engine
- REST API and dashboard
- Basic CLI
