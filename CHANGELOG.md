# Changelog

## [1.0.0-rc.1] — 2026-03-18

Release candidate. The first version where the full loop works end-to-end: agents register permissionlessly, submit trading signals, get scored against real market outcomes, and build on-chain reputation via ERC-8004.

~130 PRs since beta.8 across every layer of the stack.

### Highlights

- **Signal Producer Interface (SPI)** — permissionless agent registration, signal submission, lifecycle state machine with slash conditions, auto-promotion, and CLI onboarding wizard (#424–#427)
- **ERC-8004 On-Chain Identity** — Identity, Reputation, and Validation registries deployed on Base mainnet; on-chain reputation scores anchored to Ethereum addresses (#356)
- **Signal Resolution** — daemon automatically scores signals against real market outcomes every 15 minutes; wired into scheduler lifecycle (#459)
- **Agent Discovery** — `.well-known/agent-registration.json`, `/llms.txt` at API root, MCP server, `CONTRIBUTING.md`, issue templates for autonomous agent onboarding (#456, #457, #460–#461)
- **Paper Trade Engine** — multi-position per symbol, 72h time-stops, kill switch integration, benchmark comparison on close (#439, #441)
- **DeerFlow Integration** — signal class taxonomy, artifact store, distribution pipeline, scheduled research triggers, skill pack (#334–#343)
- **Dashboard Overhaul** — 5 UX sprints: beeswarm signals, conviction gauge, equity curve, forecasts page, vitals bar, Inter font, semantic colors, design tokens (#349–#352)

### Added

**SPI / External Producers**
- External adapter framework with `post-fiat-signals` reference producer (#424)
- Producer lifecycle state machine — slash conditions, auto-promotion after performance threshold (#425)
- `b1e55ed spi` CLI commands + interactive producer onboarding wizard (#426)
- External producer guide and interface spec (#427)
- `SPEC_INLINE` support for binary installs — specs travel with the producer (#449)
- Adaptive forge onboarding with machine estimation (#455)
- Signal resolution wired to daemon scheduler — 15-min auto-scoring loop (#459)

**ERC-8004 / On-Chain**
- Identity, Reputation, and Validation registries (Base mainnet) — ERC-8004 compliant on-chain identity for agents and operators (#356)

**Brain / Execution**
- Runtime universe bundles with dashboard filters and wizard starter packs (#379, #380, #381)
- Bundle-aware gating for auto trade intents — only trade symbols in active bundles (#380)
- Paper mode throughput — multi-position per symbol, 72h time-stop, position monitor stop/target evaluation (#439, #441)
- Benchmark comparison wired into position close flow (#440)
- Brain cycle auto-scheduler + dashboard signal scoring (#361)
- yFinance + Twelve Data price feed, TradFi symbols UI in settings (#392)
- `b1e55ed doctor` + E2E test suites (#353)

**Dashboard**
- Sprint 2: beeswarm signals, producer cards, conviction gauge, equity curve, sentiment horizons (#349)
- Sprint 3: forecasts page, calibration view, discretionary signals panel (#350)
- Sprint 4: Inter font, semantic colors, ghost charts, onboarding flow (#351)
- Sprint 5: vitals bar, signal drawer, design tokens, font purge, high-contrast, nav consolidation (#352)
- Live position marks + realtime refresh for signals/positions (#382)
- v1.0.0-beta.1 versioning scaffolding — CHANGELOG, footer, version API (#345)

**DeerFlow Integration**
- Signal class taxonomy + composable MCP tools + karma dampening (#335)
- b1e55ed skill pack for DeerFlow (#336)
- Artifact store + distribution pipeline + dashboard panel (#337)
- Harness-agnostic gateway + DeerFlow integration config + operator docs (#338, #341)
- Scheduled research trigger producer + dashboard integration (#343)

**Deployment / Daemon**
- Unified process supervisor daemon (`b1e55ed daemon`) (#297)
- Wizard systemd install with EnvironmentFile + brain cron for autonomous operation (#294, #295)
- b1e55ing runs inline in CI — never blocks merge, auto-skip housekeeping (#296)

**Config / CLI**
- `auto_paper_trade_min_magnitude` exposed as documented config item (#431)
- Inline comments on all config YAML files (#432)

**Docs / Whitepapers**
- Whitepaper v4 final — falsification test, difficulty-adjusted sharpness, adversarial model (#279, #280)
- Setup guide — OpenClaw + b1e55ed installation (#277)
- Full doc pass — restructure nav, wire orphans, remove stubs (#434)
- Agent discovery — README, CONTRIBUTING, llms.txt, issue templates (#457)
- Consolidate env templates, remove hardcoded IP, add onboarding guidance (#460)
- Paper trade banner, ERC-8004 section, agent card in intro (#461)

### Fixed

**Attribution / Karma**
- Wired `conviction_id` through full position open → close → karma loop (#443–#445)
- Fixed `source_event_ids` flywheel — query DB for signal attribution instead of relying on payload guard (#403, #407, #409)
- `ATTRIBUTION_GAP_V1` fallback for missing attribution + TemplateResponse deprecation warnings (#412)
- Contributor `signal accepted=1` correctly set after brain cycle (#443)

**Dashboard**
- P&L colors: correct neg=red/pos=green/zero=dim across all views (#428–#430)
- Live price fallback for positions missing `price_ws` signal (#420)
- Conviction gauge normalization + signal timeline null-ts scatter fix (#421)
- Signal timeline: hourly bucketed sampling, 24h window, top-10-per-hour spread (#422, #423)
- Performance trade history, closed position UX, PnL colors (#390)
- Signal timeline, producer health, conviction-position conflict (#385)
- Brain run timeout + bundle delete HTMX target fix (#396)
- Hide fake settings + fix close refresh + accurate verify message (#406)
- Nav overflow dropdown + contrast fixes (#360, #362)
- UX sprints: consolidate pages, merge brain+cockpit, fix empty states, discretionary form (#364, #366)
- Wire brain controls and make settings actions truthful (#370)

**Brain / Execution**
- OMS injection in brain scheduler — add preflight and sizer (#388, #389)
- Short stop-loss/take-profit price math corrected (#383)
- Short risk levels, HYPE data sources, dedupe tolerance, bearish conviction bias (#384)
- Live PnL, engine gates, auto-close, signal arrows (#386)
- Restore auto intents and correct OMS doctor signal; inject OMS into brain run paths (#377, #375)
- Raw timestamps preserved for timeline plotting (#378)
- Wire OMS, real mid_price, config repair, conviction_id linkage (#354)
- Stale conviction scores + TradFi config hot-reload (#394)
- Stale universe on forecasts page + correct bundle pack symbols (#395)

**Database / Infrastructure**
- SQLite WAL mode + busy_timeout + created_at/symbol indexes (#401)
- Single authoritative `get_db_path()` — all surfaces route through config (#414)
- `INSERT OR IGNORE` on event_dedup to prevent brain-full crash on duplicate keys (#448)
- Atomic event emission + crash reconciliation (#404)
- Wire reconcile to daemon startup + CLI + mark placeholder events (#411)
- Wire prune scheduler — retention now automatic per `prune_interval_seconds` (#417)
- Brain cycle freshness + kill switch added to health check — degrade on stale (#419)
- Ungate maintenance/recovery commands from identity requirement (#416)
- Register reconcile subparser + fix setup repair kill-switch event type (#415)

**Deployment / Daemon**
- Production install hardening — dashboard auth, Binance 451, learning race (#326)
- Identity gate double-nesting, config root resolution for uv tool installs (#321–#325)
- `engine.core.paths` — single source of truth for `~/.b1e55ed` (#323)
- API reads DB from `data_dir()` not `Path.cwd()/data` (#327)
- Operator bugs batch: data dir, dashboard routes, status crash, wizard UX (#318, #319)
- Operator UX improvements + onboarding critical path fixes (#306, #307)
- Wizard: skip re-registration on 409, stop duplicate GH issues, env vars + systemd (#285–#295)

**Polymarket**
- Update `WATCHLIST_SLUGS` to active 2026 markets (#446)
- Independent `p_true` estimation — GBM + near-resolution + spread-anomaly models (#452)

**Other**
- Yahoo Finance candle feed for equities; graceful degradation on endpoint unavailability (#450)
- Scoring universe derived from enabled bundles (#442)
- Data pruning + karma event-sourcing + retention bug fixes (#402, #405)
- Producer health fallbacks, SQLite thread safety, dashboard UX (#358, #359)
- Wire producer action buttons: run-now, restart, reset-failures (#357)
- Social panel refresh and source visibility (#367, #371)
- API: capabilities and OpenAPI docs aligned with real routes; manifest route schema crash fixed (#369, #373)
- Producer identity semantics unified (#374)
- DeerFlow merge fix: restore missing endfor/table close in social.html (#339)
- Two-poll write-stability check prevents race on artifact ingestion (#342)
- b1e55ing CI: bless PRs without mutating head SHA; blessing commits must not suppress CI (#291, #376)
- Full system audits — dashboard rendering, engine pipeline, mock test harness (#391, #393, #397)

### Changed

- Repo sweep — remove internal docs, hardcoded IPs, stale files (#458)
- Root cleanup — remove DIAGNOSIS.md, update roadmap/skill version, fix stale crons (#435)
- Move internal specs to `docs/internal/`, remove UX artifacts and superseded .md files (#436)
- Foundation cleanup — StrEnum dedup, HTMX path normalize, dead code removal (#398–#400)
- Auto-update dependency graphs (#278, #281, #286)
- CODEX.md agent quick-reference and `codex-init.sh` baseline script (#453)
- SPI manifest onboarding pointed to producer flow (#454)
- MCP docs aligned with current tool contract (#372)
- DeerFlow integration plan v2 documentation (#334, #340)
- Consolidate SPI docs into producers section, merge nav groups (#433)

---

## v1.0.0-beta.8 — Flywheel Sprints (S0–S7)

### Highlights

Closed the signal → trade → outcome → attribution loop. The flywheel now compounds: every trade updates producer karma, which updates synthesis weights, which produces better signals.

### Features

- **Signal contract schema** (S0) — `FLYWHEEL_SPEC.md`, `SIGNAL_ACCEPTED_V1` and `ATTRIBUTION_OUTCOME_V1` event types, `POST /api/v1/signals/validate` endpoint
- **Attribution layer** (S1) — `SIGNAL_ACCEPTED_V1` emitted on every synthesis acceptance, linking signals to trades
- **Karma wiring** (S2) — Position close → `attribute_outcome()` → `producer_karma` table update (EMA α=0.05)
- **Smart TradFi producer** (S3) — Self-contained Binance API calls, rule-based direction + confidence scoring
- **Benchmark producers** (S4) — 4 benchmarks (momentum, flat, equal-weight, discretionary) + `POST /api/v1/benchmarks/discretionary`
- **Kill switch conditions** (S5) — All 5 conditions wired: consecutive losses (3), single loss >2%, open risk >5%, data feed degradation, fill divergence >0.5%
- **Cockpit dashboard** (S6) — `/cockpit` with 4-quadrant "what do I trade today" view, HTMX 30s auto-refresh, `GET /api/v1/cockpit/state`
- **Auto-paper-trade** (S7) — Opens paper trades automatically on confidence ≥ 0.65; `StratificationTracker` for 30-day proof; `b1e55ed report --stratification` and `b1e55ed report --cockpit-summary` CLI commands

### New database tables

- `producer_karma` — per-producer karma scores
- `signal_stratification` — confidence band outcome tracking
- `discretionary_signals` — operator override signals
- `system_state` — kill switch and cockpit state

### New configuration

- `brain.auto_paper_trade: bool` (default `true`) — auto-open paper trades on high confidence

### Breaking changes

None.

---

## v1.0.0-beta.7 — 2026-02-28

### Highlights

Two explicit operator deployment modes with guided setup. Full documentation site live at docs.b1e55ed.permanentupperclass.com. Multiple stability and packaging fixes from internal testing.

---

### Features

- **`b1e55ed setup standalone` / `b1e55ed setup connected`** — operator setup now has two explicit paths. `standalone` runs b1e55ed as a self-contained CLI + dashboard node. `connected` adds OpenClaw + Telegram orchestration for AI-driven operation via chat. Prompts interactively if no mode is specified; defaults to `standalone` in non-interactive and CI environments. (#124, #129)
- **Mintlify documentation site** — full docs live at `docs.b1e55ed.permanentupperclass.com`. Covers quickstart, operator guides, producer configuration, oracle setup, API reference, and agent interfaces. (#123, #126, #128)
- **Agent-first discoverability** — `docs/llms.txt` machine-readable discovery index for AI crawlers and LLM agents; MCP contextual integration (Cursor, VS Code, Claude); dedicated agents page covering oracle queries, SSE streaming, signal submission, and auth model. (#128)
- **Interactive setup scripts** — `setup-standalone.sh` and `setup-connected.sh` (renamed from `setup-agent.sh` to eliminate naming ambiguity with AI agents that query the oracle). (#124, #129)

---

### Fixes

- **Oracle URL** — updated to `oracle.b1e55ed.permanentupperclass.com` across all references. (#125)
- **EAS enabled by default** — Ethereum Attestation Service attestations now active on install without manual configuration. API root route fixed. `repo_root` correctly resolved when b1e55ed is installed as a uv tool rather than run from source. (#108)
- **uv tool reinstall** — added `--refresh` flag to force re-fetch git cache on reinstall, preventing stale package versions. (#110)
- **Single-source versioning** — `bump-version.sh` owns the canonical version; release workflow and forge binary auto-build both derive from it. Eliminates version drift between `pyproject.toml`, lockfile, and release artifacts. (#114)
- **Dashboard 500** — fixed crash on dashboard load for fresh installs. Contributor registration endpoint repaired. `b1e55ed start` command robustness improved. (#115)
- **Audit fixes** — config packaging corrected (files were excluded from wheel), `slots __dict__` attribute access fixed, `b1e55ed start` made more robust against missing config keys. (#117)
- **Contributor registration wizard** — now shows the actual error on failure instead of a silent generic fallback; fallback logic correctly handles partial success. (#119)
- **Forge timing display** — elapsed time shown during identity forge is now accurate (real seconds, not the previous hardcoded "~2 seconds"). (#107)
- **Oracle setup documentation** — removed incorrect instruction for operators to set `B1E55ED_GITHUB_APP_KEY`. That key is held exclusively by the managed oracle server operator (PUC). Operators need zero extra configuration — oracle routes activate automatically when b1e55ed starts. (#131)

---

### Documentation

- **Operator guides** — standalone and connected guides covering installation, first-run setup, systemd service configuration, and ongoing operations. (#121)
- **Producer configuration guide** — covers producer registration, symbol packs, tuning parameters, and sample configurations for common data sources. (#122)
- **docs.json v4 schema** — Mintlify configuration migrated from `mint.json` to `docs.json` with correct v4 schema (navigation as object, valid color tokens, sequoia theme, JetBrains Mono font). (#126)
- **Terminology** — *operators* (humans running b1e55ed), *AI agents* (external software querying the oracle), and deployment modes (*standalone* / *connected*) are now explicitly defined and used consistently throughout docs and the marketing site. (#129)
- **SEO** — canonical URLs, Open Graph images (1200×630), Twitter cards, JSON-LD schemas, sitemaps, and `robots.txt` across all four PUC domains. AI crawlers explicitly welcomed.

---

### Breaking changes

None. All changes are additive or bug fixes.

---

### Upgrading from beta.6

```bash
uv tool install --refresh b1e55ed
b1e55ed --version  # should print 1.0.0-beta.7
```

If running as a systemd service:

```bash
sudo systemctl restart b1e55ed.service
```

## v1.0.0-beta.6 — 2026-02-27

macOS install fixes: stale uv git cache, shell env var scoping bug, EAS on by default, API root info page, dashboard identity path when installed as a uv tool. 589 tests passing.

### 🔴 Bug Fixes

- **Branch install syntax** — `BRANCH=develop curl ... | bash` was wrong: the env var only applies to `curl`, not `bash`. Correct form: `curl ... | BRANCH=develop bash`. install.sh comment, docs, and CHANGELOG all updated.
- **uv git cache** — `install.sh` now passes `--refresh` to `uv tool install`; prevents stale cached git clone from serving old code after `uninstall` + reinstall on a branch
- **Dashboard identity gate** — `_repo_root()` in all dashboard modules was using `Path(__file__).resolve().parents[1]` (uv tool install dir, not user's cwd); always showed "forge required" even after identity already forged. Fixed to use `B1E55ED_REPO_ROOT` env var or `Path.cwd()` (same as CLI)
- **EAS enabled by default** — `EASConfig.enabled = True` (was `False`); off-chain attestations need no `rpc_url` and should always be on. Startup log now shows helpful hint instead of scary DISABLED warning
- **Forge timing** — Banner and wizard said "~2 seconds" (Apple Silicon benchmark); Intel Macs take 30s–2min. Updated to "seconds to ~2 min depending on hardware"

### 🟡 API

- **`GET /` info page** — API root was 404; now returns JSON with version, docs link, and key endpoint map

### 🔧 CI / Workflow

- **Branch guard added** — `.github/workflows/branch-guard.yml` blocks PRs to `main` from any branch except `develop` or `release/*`; enforces the develop → main release flow


## v1.0.0-beta.5 — 2026-02-26

macOS onboarding, Rust forge binary distribution, and zero-credential contributor registration via oracle relay. 589 tests passing.

### 🟡 Install & Onboarding

- **macOS install fixed** — `install.sh` now bootstraps Python via `uv` if none found; suppressed stderr noise; `eth-account>=0.11` moved to default deps (no longer requires `[eas]` extra)
- **Forge binary auto-download** — `install.sh` and wizard both auto-download the Rust forge binary for macOS (universal arm64+x86_64) and Linux x86_64 from the latest release
- **Pre-release URL fix** — `/releases/latest` skips pre-releases; both installer and wizard now resolve the real latest tag via `GET /releases?per_page=1` and build explicit download URLs
- **Universal macOS binary** — CI builds a single `b1e55ed-forge-macos` via `lipo` (arm64 + x86_64); works on both Apple Silicon and Intel without selecting the right binary
- **`install.sh` supports `BRANCH` env var** — `BRANCH=develop curl -sSf .../install.sh | bash` installs from any branch for testing

### 🟡 Wizard UX

- **Symbol packs menu** — Interactive preset selection instead of raw comma list
- **GitHub token prominence** — Token field highlighted; explains why it's needed
- **Real version in banner** — Uses `importlib.metadata.version("b1e55ed")` instead of hardcoded `v1.x`
- **Forge banner aligned** — Width matches wizard banner (42 chars), text centered
- **Health check test step** — Step 5 now runs `b1e55ed health` (was `brain --symbols BTC --dry-run` which doesn't exist)

### 🟡 Contributor Registration

- **Auto-registration in wizard** — New step `[4b]` after config: inline `ContributorRegistry.register()` call; no subprocess, no PATH issues
- **Oracle relay** — Wizard calls `oracle.b1e55ed.xyz/api/v1/oracle/contributors/register`; oracle holds GitHub App key and creates announcement issue server-side; new users need zero credentials
- **New public oracle endpoint** — `POST /api/v1/oracle/contributors/register` (no auth); validates `eth:0xb1e55ed` prefix; idempotent (409 on duplicate)
- **GitHub App auth wired** — `get_publisher()` and `_build_contributor_registry_with_eas()` now activate on `app_id > 0`, not just `token`; App auth was previously silently skipped

### 🟡 CLI

- **`b1e55ed uninstall`** — New CLI command + `uninstall.sh`; documented in `docs/cli-reference.md`
- **GitHub App defaults** — App ID `2953603`, Installation ID `112556330` baked into `engine/config/github_app_defaults.py`
- **Version sync** — `engine/__init__.py` uses `importlib.metadata.version("b1e55ed")` (no hardcoded version string)

### 🔧 CI

- **No direct pushes to main** — Workflows (`dep-graphs`, `b1e55ing-merge`) create PRs instead of committing directly
- **Forge release permissions** — `forge-release.yml` now has `contents: write` permission
- **Manual forge trigger** — `workflow_dispatch` on forge-release accepts `tag_name` input
- **CLI doc coverage check** — CI fails if a new command is added without a `docs/cli-reference.md` entry

---

## v1.0.0-beta.4 — 2026-02-25

Customer readiness release. 8-reviewer audit (Stripe, Coinbase, Cloudflare, Palantir — two model sets). Every finding addressed. 583 tests passing.

### 🔴 Security & Data Integrity

- **Config secret leak fixed** — `GET /config` now recursively redacts all sensitive fields (token, key, secret, password, private_key) before returning
- **Rate limiter TOCTOU fixed** — Replaced SELECT+INSERT race with atomic `INSERT ... ON CONFLICT DO UPDATE` upsert; concurrent requests can no longer cause 500 storms at window boundaries
- **Global exception handler** — Unhandled exceptions now return `{"error": {"code": "internal_error", "request_id": "..."}}` instead of leaking raw stack traces or `{"detail": "..."}`
- **Request ID middleware** — Every request gets an `X-Request-ID` header (generated or propagated); included in all error responses for incident correlation

### 🔴 Karma Data Model

- **Double-spend prevention** — `karma_intents.trade_id` now has `UNIQUE` constraint + DB migration; `INSERT OR IGNORE` on retries
- **Contributor attribution** — `karma_intents.contributor_id` column added; `close_position()` resolves contributor via `conviction_id → conviction_scores → contributors` chain; per-contributor karma now computable directly
- **Hash v2 — `contributor_id` in hash** — Attribution included in hash computation; operator cannot change who gets credit without breaking the chain
- **`profitable` field wired** — `ContributorScoring.update_outcomes()` now called on every position close; `hit_rate`, `calibration` scoring factors are real, not zero-initialized
- **Crash recovery sweep** — `recover_missing_karma_intents()` runs at startup and brain cycle; closed positions without karma intents are reconciled automatically

### 🟠 Attribution Integrity

- **Real `chain_verified`** — Oracle provenance now calls `verify_hash_chain(fast=True, last_n=100)` instead of `hash IS NOT NULL`; semantics documented in `docs/oracle.md`
- **Accepted audit events** — `SIGNAL_ACCEPTED_V1` emitted into hash-chained log on every synthesis acceptance; operator cannot silently flip `accepted` without a detectable trace
- **Deterministic score replay** — `compute_score()` and `leaderboard()` accept `as_of: datetime` parameter; contributor score disputes are now reproducible
- **Signal visibility endpoint** — `GET /api/v1/contributors/{id}/signals` — contributors can see which signals were accepted or rejected
- **Export karma fixed** — `b1e55ed export karma` now queries `karma_intents JOIN contributors`; previous version queried nonexistent JSON fields

### 🟠 Pagination & Observability

- **All list endpoints paginated** — `/contributors`, `/positions`, `/karma/intents`, `/contributors/leaderboard` accept `?limit=` and `?offset=`; leaderboard capped at 200; N+1 query replaced with 4 batch queries
- **SSE stream OOM fixed** — Historical replay uses paginated cursor (500 events/page) instead of single `fetchall()`
- **Real health endpoint** — Returns DB connectivity, brain cycle age (minutes), kill switch level; HTTP 503 on DB failure
- **Prometheus `/metrics`** — `b1e55ed_contributors_total`, `b1e55ed_brain_cycles_total`, `b1e55ed_karma_intents_total`, `b1e55ed_karma_settled_total`, `b1e55ed_signals_total`, `b1e55ed_positions_total`

### 🟡 Install & Onboarding

- **`install.sh`** — Curl-pipeable one-liner installer: installs uv, installs b1e55ed as a uv tool, adds `~/.local/bin` to PATH; works on macOS and Ubuntu; idempotent
- **`b1e55ed wizard`** — 5-step interactive onboarding: identity forge → config → producer registration → brain first run → API setup; stdlib only, no new dependencies
- **`./b1e55ed` wrapper** — Repo-root script for from-source contributors; skips `uv run` prefix
- **README updated** — Primary install path now `curl ... | bash && b1e55ed wizard`

### 🟡 Docs & UX

- **KARMA-SPEC.md rewritten** — Replaced EMA formula with accurate 5-factor composite spec matching `engine/core/scoring.py` (hit_rate 35%, calibration 20%, volume 20%, consistency 15%, recency 10%)
- **Identity recovery documented** — New `docs/identity.md`; new `b1e55ed identity restore --eth-key <hex>` CLI command; Ed25519 key is deterministically recoverable from Ethereum key via HKDF
- **Consistent error format** — `karma.py` and `positions.py` migrated from `HTTPException` to `B1e55edError`
- **CLI reference updated** — Added `b1e55ed wizard`, `b1e55ed identity restore`; corrected source path from `engine/cli.py` → `engine/cli/main.py`

---

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
