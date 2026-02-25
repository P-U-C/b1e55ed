# Changelog

## v1.0.0-beta.3 — 2026-02-25

### Added

**Backtest engine (B1a–B1h)**
- Walk-forward backtests with FDR correction (`b1e55ed backtest walkforward`)
- Parameter grid sweep across all strategy × parameter combinations (`b1e55ed backtest gridsweep`)
- Multi-strategy mega sweep with FDR across all combos × all assets (`b1e55ed backtest megasweep`)
- Regime-conditioned backtests with per-regime FDR (`b1e55ed backtest regime`)
- Dynamic Kelly criterion sizing from trade history (`b1e55ed kelly`)
- 10 backtest strategies: momentum, MA crossover, RSI reversion, mean reversion, trend following, breakout, volatility, funding arb, combined
- Walk-forward validation, OOS splits, FDR-corrected survivors

**Agent interfaces (AG1)**
- SSE event stream: `GET /api/v1/events/stream` — real-time event feed with domain filter and resume
- MCP server: `POST /api/v1/mcp` — JSON-RPC 2.0 with 6 tools
- Signal attribution: `GET /api/v1/signals/{id}/attribution`
- Producer feedback channel: `POST /api/v1/producers/{id}/feedback`
- Capability discovery: `GET /api/v1/capabilities`
- Trace sessions: create, list, get, delete stateful agent sessions

**CLI decomposition (AG2)**
- CLI refactored from single file into package structure (`engine/cli/`)
- Full backward compatibility via re-exports

**Signal normalization (SQ1)**
- Asset-aware on-chain signal normalization
- Whale signal threshold: 0.1% of market cap = full signal
- Exchange flow threshold: 0.5% of daily volume = full signal

**External auditability (E1)**
- `b1e55ed anchor [--eas]` — print current hash-chain root, optionally anchor to EAS
- `b1e55ed export karma [--format jsonl|json|csv] [--include-chain]` — export karma attribution data
- `b1e55ed replay` — rebuild projections from event log
- `b1e55ed integrity` — verify hash chain integrity
- GitHub auto-publish: on contributor registration, optionally opens a GitHub issue as a public record
- `GET /contributors/{id}/attestation` — returns `published` field

**Oracle provenance layer (OR1)**
- `GET /api/v1/oracle/producers/{id}/provenance` — public endpoint, no auth required
- Anti-Goodhart response header on every oracle response
- `b1e55ed_provenance_check` MCP tool — check producer lineage before acting on a signal
- Anonymized query logging to `data/oracle_queries.jsonl` (demand intelligence, never feeds karma)
- `docs/KARMA-SPEC.md` — karma score specification
- `docs/SEED_MANIFEST.md` — reproducibility proof stub

**Easter egg hook (b1e55ing)**
- `scripts/b1e55ing.py` — auto-injects cultural references into every PR commit
- GitHub Actions signal: PR open triggers direct Telegram notification to agent for immediate blessing
- Post-merge fallback workflow as hard guarantee
- 27 tests

**Documentation**
- Complete documentation sweep: 15 operator-facing guides
- New: `docs/oracle.md`, `docs/agent-interfaces.md`, `docs/curator.md`, `docs/backtest.md`
- `docs/internal/` — design specs and sprint plans moved out of operator docs
- Code dependency graph: 174 modules mapped across 7 layers
- CI auto-update: `dep-graphs.yml` keeps dependency graphs current on every push

### Changed

- CLI package structure (backward compatible)
- `GET /contributors/{id}/attestation` includes `published` field
- Signal normalizer wired into on-chain domain score path

### Tests

530 tests passing. Full CI: tests (3.11 + 3.12), lint, typecheck, build, security, smoke, shellcheck, brand, doc-deps, code-deps, completeness, links.

---

## v1.0.0-beta.2 — 2026-02-19

- Operator layer sprint plan (O1-O4)
- Karma treasury and settlement workflow
- Contributor attestation via EAS (off-chain)
- Kill switch multi-level gating
- Regime detection and conviction scoring
- Paper trading mode

## v1.0.0-beta.1 — 2026-02-10

- Initial release
- Event-sourced database with hash chain
- Brain synthesis engine
- REST API and dashboard
- Contributor registry
- Basic CLI
