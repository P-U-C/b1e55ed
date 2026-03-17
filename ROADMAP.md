# b1e55ed Roadmap

Version progression from beta to production-ready release.

---

## Version Gates

### v1.0.0-beta.1 ✅ SHIPPED — 2026-02-10
**Status:** Initial release

**What shipped:**
- ✅ Append-only event store with hash chain
- ✅ Brain synthesis engine (6-phase: collection → quality → synthesis → regime → conviction → decision)
- ✅ REST API and web dashboard (HTMX + Jinja2, CRT aesthetic)
- ✅ Basic CLI
- ✅ OMS integration (Hyperliquid paper/live, preflight checks)
- ✅ Kill switch (5 levels, auto-escalate, operator-only de-escalate)
- ✅ Historical data (5+ years BTC/ETH/SOL/SUI/HYPE + funding + Fear & Greed)
- ✅ Docker deployment
- ✅ 150+ tests

---

### v1.0.0-beta.2 ✅ SHIPPED — 2026-02-19
**Status:** Operator layer foundation

**What shipped:**
- ✅ OpenClaw integration spec (operator layer)
- ✅ Karma treasury and settlement engine
- ✅ EAS off-chain attestations
- ✅ Kill switch multi-level gating (L0–L4)
- ✅ Regime detection and conviction scoring
- ✅ Paper trading mode
- ✅ Contributor registry and scoring

---

### v1.0.0-beta.3 ✅ SHIPPED — 2026-02-25
**Status:** 226 commits. 583 tests. Full CI green.

**What shipped:**
- ✅ Security hardening: Argon2id KDF, AES-256-GCM, unified Ed25519/secp256k1 identity, rate limiting, kill-switch auth isolation
- ✅ Role-based permissions (operator, agent, tester, curator) + authority model (single-writer enforcement)
- ✅ Karma settlement governance: multi-step workflow, threshold controls, settlement history
- ✅ Producer hardening: response size caps, JSON schema guard, quarantine/auto-recovery
- ✅ Signal quality: anti-gaming scoring, anti-spam rate limiting, asset-aware normalization
- ✅ Social intelligence pipeline: Farcaster, Reddit, TikTok, Google Trends, Fear & Greed, Polymarket
- ✅ TradFi data: FRED, Yahoo Finance, SEC EDGAR (Form 4/13F/8-K), OpenInsider
- ✅ Feature store with frozen snapshots and data quality monitoring
- ✅ Backtest engine: 10 strategies, 96K+ parameter sweep, walk-forward validation, FDR correction
- ✅ Agent interfaces: SSE event stream, MCP server (6 tools, JSON-RPC 2.0), signal attribution, producer feedback, trace sessions
- ✅ Oracle provenance layer: public endpoint, chain verification, attribution windows
- ✅ CLI decomposition into `engine/cli/` package
- ✅ Code dependency graph (174 modules, 7 layers, CI validation)

---

### v1.0.0-beta.4 ✅ SHIPPED — 2026-02-25
**Status:** Customer readiness — 8-reviewer audit (Stripe, Coinbase, Cloudflare, Palantir). 583 tests.

**What shipped:**
- ✅ Security: config secret redaction, rate-limiter TOCTOU fixed (atomic upsert), global exception handler, request ID middleware
- ✅ Karma data model: double-spend prevention (UNIQUE constraint), contributor attribution in hash, `profitable` field wired, crash recovery sweep
- ✅ Attribution integrity: real `chain_verified`, accepted audit events (`SIGNAL_ACCEPTED_V1`), deterministic score replay, signal visibility endpoint
- ✅ All list endpoints paginated; SSE stream OOM fixed (cursor pagination); real health endpoint (DB + brain cycle age + kill switch); Prometheus `/metrics`
- ✅ `install.sh` curl-pipeable one-liner; `b1e55ed wizard` 5-step interactive onboarding
- ✅ KARMA-SPEC.md rewritten (5-factor composite: hit_rate 35%, calibration 20%, volume 20%, consistency 15%, recency 10%)
- ✅ Identity recovery: `b1e55ed identity restore`, Ed25519 key derivable from Ethereum key via HKDF

---

### v1.0.0-beta.5 ✅ SHIPPED — 2026-02-26
**Status:** macOS onboarding, Rust forge binary, zero-credential contributor registration. 589 tests.

**What shipped:**
- ✅ macOS install fixed (Python via uv bootstrap, eth-account in default deps)
- ✅ Forge binary auto-download (universal macOS arm64+x86_64, Linux x86_64) from latest release
- ✅ `install.sh` supports `BRANCH` env var
- ✅ Wizard UX: symbol packs menu, GitHub token prominence, real version in banner, health check step
- ✅ Oracle relay for contributor registration (no GitHub token required for new operators)
- ✅ `POST /api/v1/oracle/contributors/register` public endpoint
- ✅ `b1e55ed uninstall` CLI command + `uninstall.sh`
- ✅ No direct pushes to main (CI workflows now create PRs)

---

### v1.0.0-beta.6 ✅ SHIPPED — 2026-02-27
**Status:** macOS install fixes and stability hardening. 589 tests.

**What shipped:**
- ✅ Branch install syntax fixed (`BRANCH=develop curl ... | bash` scoping)
- ✅ uv git cache: `--refresh` flag on install to prevent stale package versions
- ✅ Dashboard identity gate: fixed `_repo_root()` to use `B1E55ED_REPO_ROOT` env or `Path.cwd()` instead of uv tool install dir
- ✅ EAS enabled by default (`EASConfig.enabled = True`)
- ✅ Forge timing display corrected (Intel Macs: 30s–2min, not "~2 seconds")
- ✅ `GET /` API root info page (was 404)
- ✅ Branch guard CI: blocks PRs to `main` from branches other than `develop` or `release/*`

---

### v1.0.0-beta.7 ✅ SHIPPED — 2026-02-28
**Status:** Two explicit deployment modes, full documentation site live.

**What shipped:**
- ✅ `b1e55ed setup standalone` / `b1e55ed setup connected` — two explicit operator deployment modes with guided setup
- ✅ Mintlify documentation site at `docs.b1e55ed.permanentupperclass.com` — quickstart, operator guides, producer config, oracle, API reference, agent interfaces
- ✅ `docs/llms.txt` machine-readable discovery index; MCP contextual integration (Cursor, VS Code, Claude)
- ✅ `setup-standalone.sh` and `setup-connected.sh` (renamed from `setup-agent.sh`)
- ✅ Oracle URL updated to `oracle.b1e55ed.permanentupperclass.com`
- ✅ EAS and API root route fixes; `repo_root` resolved correctly when installed as uv tool
- ✅ Single-source versioning via `bump-version.sh`; eliminates version drift
- ✅ Dashboard 500 on fresh install fixed; contributor registration wizard shows real errors
- ✅ SEO across all four PUC domains (canonical URLs, Open Graph, JSON-LD, sitemaps)

---

### v1.0.0-beta.8 — In Flight
**Status:** SPI lifecycle/CLI, dashboard fixes, full doc pass, config annotations

**In progress:**
- 🔄 SPI producer lifecycle: `b1e55ed producer` CLI commands (register, list, status, quarantine/release)
- 🔄 Dashboard fixes: P&L display, live data SSE wiring, cockpit refinements
- 🔄 Full documentation pass: all pages reviewed against current codebase
- 🔄 Config YAML inline annotations across all config files
- 🔄 Flywheel sprints (S0–S7): signal contract schema, attribution layer, karma wiring, smart TradFi producer, benchmark producers, kill switch conditions, cockpit dashboard, auto-paper-trade

---

### v1.0.0-rc.1 — Validation Gate
**Gate:** 30 days paper trading with positive expected value

**Requirements:**

1. **Paper Trading Validation** (30 days minimum)
   - [ ] 100+ signals generated across all assets
   - [ ] Conviction calibration working (high conviction → higher win rate)
   - [ ] Positive expected value on paper trades
   - [ ] No critical bugs discovered
   - [ ] Max drawdown <30%

2. **Learning Loop Proven**
   - [ ] Domain weights have auto-adjusted at least once
   - [ ] Producer scores reflect actual performance
   - [ ] Scorecard generation (per-producer, per-strategy hit rates)
   - [ ] Documented improvement over baseline

3. **Production Infrastructure**
   - [ ] Structured logging (JSON, retention policy)
   - [ ] Backup/restore procedures tested
   - [ ] Alert system battle-tested (no false positives/negatives)
   - [ ] Installation tested on 3+ different environments

4. **Performance Baseline**
   - [ ] Sharpe ratio >0.5 on combined portfolio
   - [ ] Win rate >55% on high-conviction signals (7-10)
   - [ ] Uptime >99% over 30 days
   - [ ] All cron jobs firing on schedule

---

### v1.0.0 — First Stable Release
**Gate:** First profitable trade with real capital

**Requirements:**

1. **Live Capital Deployment** ($1K-$5K initial)
   - [ ] At least 10 live trades executed
   - [ ] Net positive P&L
   - [ ] Zero position/leverage violations
   - [ ] Zero critical execution errors

2. **Community Ready**
   - [ ] Installation works reliably for new users (human and agent)
   - [ ] Common deployment issues documented
   - [ ] Video walkthrough (optional)
   - [ ] At least 1 external contributor or agent integration

---

## Future (Post-1.0.0)

| Feature | Priority | Description |
|---------|----------|-------------|
| Multi-exchange support | High | Binance, Bybit, dYdX beyond Hyperliquid |
| Cross-asset correlation | High | Portfolio-level risk accounting |
| Strategy marketplace | Medium | Share/download strategies from community |
| Mobile dashboard | Medium | Responsive design for phone monitoring |
| Backtesting UI | Medium | Web interface for parameter sweeps |
| Voice alerts | Low | TTS notifications via OpenClaw |
| Paper trading leaderboard | Low | Public scoreboard for beta testers |

---

## Tech Debt

| Item | Priority | Notes |
|------|----------|-------|
| CI Docker Compose test | High | Currently bypassed (YAML validation only) |
| Dynamic universe | Medium | Auto-add new listings, remove delisted |
| Multi-exchange abstraction | Medium | Exchange interface beyond Hyperliquid |
| Prometheus metrics | Low | Export for Grafana monitoring |

---

## Release Schedule

| Version | Date | Status |
|---------|------|--------|
| **v1.0.0-beta.1** | 2026-02-10 | ✅ SHIPPED |
| **v1.0.0-beta.2** | 2026-02-19 | ✅ SHIPPED |
| **v1.0.0-beta.3** | 2026-02-25 | ✅ SHIPPED |
| **v1.0.0-beta.4** | 2026-02-25 | ✅ SHIPPED |
| **v1.0.0-beta.5** | 2026-02-26 | ✅ SHIPPED |
| **v1.0.0-beta.6** | 2026-02-27 | ✅ SHIPPED |
| **v1.0.0-beta.7** | 2026-02-28 | ✅ SHIPPED |
| **v1.0.0-beta.8** | TBD | 🔄 In flight |
| **v1.0.0-rc.1** | TBD | ⬜ 30-day paper validation |
| **v1.0.0** | TBD | ⬜ First profitable trade |

Gates are mandatory. Dates are targets.

---

## Success Definition

**v1.0.0 is reached when:**
1. System has generated net profit with real capital
2. Learning loop demonstrably improves over time
3. Both humans and agents can install, operate, and contribute
4. No critical bugs in 30+ days of production use

Not when the code is perfect. When it works — and when others can use it.

---

*Last updated: 2026-03-17*
