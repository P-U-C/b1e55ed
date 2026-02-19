# b1e55ed Roadmap

Version progression from beta to production-ready release.

---

## Version Gates

### v1.0.0-beta.1 (Current)
**Status:** Feature-complete, untested with real capital

**What's included:**
- ✅ Core Brain engine (6-phase: collection → quality → synthesis → regime → conviction → decision)
- ✅ 13 signal producers across 6 domains (technical, on-chain, TradFi, social, events, curator)
- ✅ Strategy framework (10 strategies, 96K+ combo sweep, walk-forward validation)
- ✅ REST API (12 endpoints, bearer auth, rate limiting)
- ✅ Web dashboard (HTMX + Jinja2, neural mesh background, CRT aesthetic)
- ✅ OMS integration (Hyperliquid paper/live, preflight checks)
- ✅ Historical data (5+ years BTC/ETH/SOL/SUI/HYPE + funding + Fear & Greed)
- ✅ Kill switch (5 levels, auto-escalate, operator-only de-escalate)
- ✅ Learning loop (domain weight auto-adjustment with bounded adaptation)
- ✅ Karma engine (optional 0.5% profit-sharing on realized gains)
- ✅ Curator pipeline (`/signal` command, auto-detection, dual-write JSONL + brain.db)
- ✅ Social intelligence (8 sources, 3-layer filter, temporal engine, contrarian signals)
- ✅ Security hardening (event hash chain, Ed25519 identity, encrypted keystore, DCG)
- ✅ 150+ tests (strict CI: lint, types, smoke, security, build)
- ✅ Documentation (12 docs, 196KB — getting started, config, API, deployment, security, architecture, developer guide, OpenClaw integration)
- ✅ Sample packs (socials, TradFi, on-chain templates)
- ✅ Docker deployment (compose + automated install script)
- ✅ Hero image + brand vocabulary enforcement

**What's not in this release:**
- ⬜ OpenClaw skill package (operator layer integration)
- ⬜ Real capital validation (all testing is paper/backtest)
- ⬜ Agent discovery (MCP/OpenAPI for agent-to-agent integration)
- ⬜ Multi-agent coordination

---

### v1.0.0-beta.2 — Operator Layer
**Gate:** Agents and humans can install and operate b1e55ed through conversation

**Requirements:**

1. **OpenClaw Skill Package**
   - [ ] `SKILL.md` — agent instructions for operating b1e55ed
   - [ ] Cron templates (brain cycle, monitoring sweep, daily summaries)
   - [ ] Heartbeat checks (position alerts, system health)
   - [ ] `/signal` chat handler (chat → curator pipeline)
   - [ ] Alert routing (engine events → chat notifications)
   - [ ] One-command install via ClawHub

2. **Agent-First Interface**
   - [ ] OpenAPI spec published at `/docs` (auto-generated, human + machine readable)
   - [ ] Structured error responses with error codes
   - [ ] Webhook subscriptions for events (agent push notifications)
   - [ ] Producer registration API (agents can add signal sources at runtime)

3. **Discoverability**
   - [ ] ClawHub listing (searchable, installable)
   - [ ] MCP server for agent discovery (optional)
   - [ ] `CONTRIBUTING.md` — how to add producers, strategies, and sample packs
   - [ ] Example: agent-as-producer tutorial

4. **Integration Testing**
   - [ ] End-to-end: chat → curator → brain → alert → chat
   - [ ] Multi-agent: 2+ agents curating simultaneously
   - [ ] Graceful degradation: operator layer down, engine continues

---

### v1.0.0-rc.1 — Validation
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

## Release Schedule (Tentative)

| Version | Target | Gate |
|---------|--------|------|
| **v1.0.0-beta.1** | 2026-02-19 | Feature-complete ← **NOW** |
| **v1.0.0-beta.2** | 2026-03-05 | Operator layer (OpenClaw skill) |
| **v1.0.0-rc.1** | 2026-04-05 | 30-day paper validation |
| **v1.0.0** | 2026-04-19 | First profitable trade |

Dates are targets, not commitments. Gates are mandatory.

---

## Success Definition

**v1.0.0 is reached when:**
1. System has generated net profit with real capital
2. Learning loop demonstrably improves over time
3. Both humans and agents can install, operate, and contribute
4. No critical bugs in 30+ days of production use

Not when the code is perfect. When it works — and when others can use it.

---

*Last updated: 2026-02-19*
