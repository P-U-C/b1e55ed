# b1e55ed Roadmap

Version progression from beta to production-ready release.

---

## Version Gates

### v1.0.0-beta.1 (Current)
**Status:** Feature-complete, untested with real capital

**What's included:**
- ✅ Core Brain engine (signal synthesis, PCS enrichment)
- ✅ 5 signal producers (RSI, Momentum, Social, Whale, Funding)
- ✅ Strategy framework (10 strategies, backtest validation)
- ✅ REST API (5 endpoints, auth, rate limiting)
- ✅ Dashboard (multi-asset monitor, signal viewer)
- ✅ OMS integration (Hyperliquid paper/live)
- ✅ Historical data (5+ years BTC/ETH/SOL/SUI/HYPE)
- ✅ 150 tests (99% coverage, strict CI)
- ✅ Documentation (29KB across 4 guides)
- ✅ Docker deployment (compose + install script)
- ✅ Release automation (GitHub Actions)

**What's missing:**
- ⬜ Real capital validation (all testing is paper/backtest)
- ⬜ Karma system (conviction tracking, outcome evaluation)
- ⬜ Sample packs (socials, tradfi, onchain templates)
- ⬜ Production monitoring (alerting, dashboards)
- ⬜ Developer docs (adding producers/sources)
- ⬜ Architecture diagrams

---

### v1.0.0-rc.1 (Release Candidate)
**Gate:** Production-ready, validated on paper trading

**Requirements:**
1. **Paper Trading Validation** (30 days minimum)
   - [ ] 100+ signals generated across all assets
   - [ ] Karma tracking for all signals (conviction → outcome)
   - [ ] Positive expected value on backtests + paper trades
   - [ ] No critical bugs discovered

2. **Karma System Complete**
   - [ ] `karma/` module implemented
   - [ ] Conviction scoring (1-10 with rationale)
   - [ ] Outcome evaluation (win/loss/neutral with metrics)
   - [ ] Scorecard generation (per-producer, per-strategy hit rates)
   - [ ] Learning loop (feedback to producers)
   - [ ] Database schema for karma events

3. **Production Infrastructure**
   - [ ] Monitoring dashboard (Grafana or similar)
   - [ ] Alert system (position monitoring, system health)
   - [ ] Log aggregation (structured logging, retention policy)
   - [ ] Backup/restore procedures
   - [ ] Disaster recovery plan

4. **Documentation Complete**
   - [ ] Architecture overview (components, data flow)
   - [ ] Developer guide (producers, sources, strategies)
   - [ ] Sample pack templates (socials, tradfi, onchain)
   - [ ] Troubleshooting guide (common issues + fixes)
   - [ ] Security hardening checklist

5. **Compliance & Safety**
   - [ ] Position size limits enforced (max 15% per asset)
   - [ ] Leverage limits enforced (max 3x)
   - [ ] Kill switch tested (DCG protection)
   - [ ] Secret management (no hardcoded keys)
   - [ ] Audit trail (all signals/trades logged)

6. **Performance Validation**
   - [ ] Backtest results documented (96K combo sweep)
   - [ ] Paper trading P&L tracked (daily, weekly, monthly)
   - [ ] Sharpe ratio >0.5 on combined portfolio
   - [ ] Max drawdown <30% on paper trades

---

### v1.0.0 (First Stable Release)
**Gate:** First profitable trade with real capital

**Requirements:**
1. **Live Capital Deployment** ($1,000-$5,000 initial)
   - [ ] At least 10 live trades executed
   - [ ] Net positive P&L (even if only $1)
   - [ ] No position limit violations
   - [ ] No leverage violations
   - [ ] No execution errors

2. **System Reliability Proven**
   - [ ] 99% uptime over 30 days
   - [ ] All cron jobs firing on schedule
   - [ ] No data loss events
   - [ ] No security incidents

3. **Karma System Validated**
   - [ ] 100+ signals with outcomes recorded
   - [ ] Hit rate tracking per producer/strategy
   - [ ] Conviction calibration working (high conviction → higher win rate)
   - [ ] Learning loop demonstrating improvement

4. **Community Ready**
   - [ ] Installation tested on 3+ different systems
   - [ ] Common deployment issues documented
   - [ ] Hero image for README (optional but nice)
   - [ ] Video walkthrough (optional but nice)

---

## Outstanding Work

### Phase 3B Completion (for beta.2)
1. **Karma System**
   - [ ] `b1e55ed/karma/` module structure
   - [ ] `karma.db` schema design
   - [ ] Conviction scoring API
   - [ ] Outcome evaluation API
   - [ ] Scorecard generator
   - [ ] CLI commands (`b1e55ed karma score`, `karma eval`, `karma report`)
   - [ ] Tests (unit + integration)

2. **Sample Packs**
   - [ ] `samples/socials/` - TikTok, Twitter, Reddit scraper templates
   - [ ] `samples/tradfi/` - CME basis, funding, ETF flows
   - [ ] `samples/onchain/` - Whale tracking, cluster detection, DEX flows
   - [ ] README per pack (what it does, how to use, API requirements)
   - [ ] Example config files (disabled by default)

3. **Developer Documentation**
   - [ ] `docs/architecture.md` - System design, components, data flow diagrams
   - [ ] `docs/developers.md` - How to add producers, sources, strategies
   - [ ] Producer template (`samples/producers/template.py`)
   - [ ] Strategy template (`samples/strategies/template.py`)
   - [ ] Testing guide (writing tests for custom components)

4. **Production Monitoring**
   - [ ] Prometheus metrics export (if using Grafana)
   - [ ] Health check endpoints (beyond basic `/health`)
   - [ ] Structured logging (JSON logs for easy parsing)
   - [ ] Alert definitions (Telegram/Discord notifications)

---

## Tech Debt

### High Priority (before rc.1)
1. **CI Docker Compose Test** - Currently bypassed (YAML validation only)
2. **Feature Vector Preservation** - Multi-dimensional signals (not just 0-10 scores)
3. **Walk-Forward Validation** - Prevent overfitting on parameter sweeps
4. **Dynamic Universe** - Auto-add new listings, remove delisted assets
5. **API Error Handling** - Graceful degradation when data sources fail

### Medium Priority (before 1.0.0)
1. **Hero Image** - README visual (current attempt was "terrible")
2. **Video Walkthrough** - Installation + first trade demo
3. **Multi-Exchange Support** - Beyond Hyperliquid (Binance, Bybit, etc.)
4. **Cross-Asset Correlation** - Account for portfolio effects
5. **Regime Detection** - Bull/bear/sideways mode switching

### Low Priority (post-1.0.0)
1. **Mobile Dashboard** - Responsive design for phone monitoring
2. **Voice Alerts** - TTS notifications via OpenClaw
3. **Backtesting UI** - Web interface for parameter sweeps
4. **Strategy Marketplace** - Share/download strategies from community
5. **Paper Trading Leaderboard** - Public scoreboard for beta testers

---

## Validation Criteria

### Paper Trading Metrics (for rc.1)
- **Duration:** 30 days minimum
- **Trades:** 100+ signals evaluated
- **Win Rate:** >55% on high-conviction signals (7-10)
- **Sharpe Ratio:** >0.5 on combined portfolio
- **Max Drawdown:** <30%
- **Uptime:** >99%

### Live Trading Metrics (for 1.0.0)
- **Capital:** $1K-$5K initial deployment
- **Trades:** 10+ executed with real money
- **P&L:** Net positive (even $1 counts)
- **Violations:** Zero (position size, leverage, DCG)
- **Errors:** Zero critical execution failures

---

## Release Schedule (Tentative)

| Version | Target Date | Gate |
|---------|-------------|------|
| **v1.0.0-beta.1** | 2026-02-19 | Feature-complete (NOW) |
| **v1.0.0-beta.2** | 2026-02-26 | Karma + samples + docs |
| **v1.0.0-rc.1** | 2026-03-19 | 30-day paper validation |
| **v1.0.0** | 2026-04-02 | First profitable trade |

**Note:** Dates are targets, not commitments. Gates are mandatory.

---

## Success Definition

**v1.0.0 is reached when:**
1. System has generated net profit with real capital
2. Karma system proves learning loop works (improving hit rates)
3. No critical bugs discovered in 30+ days production use
4. Installation works reliably for new users

Not when the code is perfect. When it works.

---

*Last updated: 2026-02-19*
