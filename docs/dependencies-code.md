# Code Dependency Graph

Module hierarchy for b1e55ed. Lower layer = more foundational. A module may only import from its own layer or below.

Enforced by `scripts/validate_code_deps.py` on every PR.

---

## Layer 0 — Primitives

No internal dependencies. Pure types, constants, base errors, and standalone utilities.

```
engine/core/events.py        Event type definitions and base event schema
engine/core/types.py         Shared type aliases and enums
engine/core/metrics.py       Metric collection primitives
engine/core/exceptions.py    Typed exception hierarchy
engine/core/time.py          UTC-aware datetime helpers
engine/core/allowlists.py    Input validation allowlists
engine/core/permissions.py   Permission flag definitions
engine/core/policy.py        Policy rule definitions
engine/security/ssrf.py      SSRF protection for outbound requests (no internal deps)
```

---

## Layer 1 — Core Infrastructure

Database, config, models, projections. Depends only on Layer 0.

```
engine/core/config.py        Pydantic config model (loaded from config/user.yaml)
engine/core/models.py        → events.py, types.py
engine/core/database.py      ⇒ models.py, events.py   (append-only + hash chain)
engine/core/projections.py   → events.py, types.py    (read projections over event log)
engine/core/client.py        → config.py              (API client)
engine/core/cache.py         → config.py
engine/core/rate_limiter.py  → config.py
engine/core/webhooks.py      → models.py, database.py
engine/core/contributors.py  ⇒ database.py, models.py
engine/core/scoring.py       ⇒ database.py
engine/core/ingestion.py     → database.py, events.py  (curator signal ingestion)
```

---

## Layer 2 — Security

Key management, identity, audit trail. Depends on Layers 0–1.

```
engine/security/identity.py   Ed25519 keypair, node identity
engine/security/keystore.py   → identity.py  (encrypted key storage)
engine/security/audit.py      → database.py  (security event log)
engine/security/redaction.py  → types.py     (PII redaction)
```

---

## Layer 3 — Producers + Data Sources

Signal generators and data collectors. Depends on Layers 0–2.

### Signal producers

```
engine/producers/base.py       Abstract base class for all producers
engine/producers/registry.py   → base.py  (producer discovery and registration)
engine/producers/ta.py         → base.py  (technical analysis: RSI, MACD, EMAs)
engine/producers/whale.py      → base.py  (on-chain large wallet moves)
engine/producers/onchain.py    → base.py  (general on-chain signals)
engine/producers/sentiment.py  → base.py  (social sentiment aggregation)
engine/producers/curator.py    → base.py, ingestion.py  (operator intel signals)
engine/producers/etf.py        → base.py  (ETF flow signals)
engine/producers/tradfi.py     → base.py  (TradFi signals: basis, funding, OI)
engine/producers/orderbook.py  → base.py  (orderbook depth signals)
engine/producers/price_ws.py   → base.py  (real-time price feed via WebSocket)
engine/producers/social.py     → base.py  (social media signal aggregation)
engine/producers/stablecoin.py → base.py  (stablecoin flow signals)
engine/producers/aci.py        → base.py  (ACI data signals)
engine/producers/events.py     → base.py  (event-driven signals)
engine/producers/template.py   (reference implementation)
```

### Backtest strategies

```
engine/backtest/strategies/base.py            Abstract strategy interface
engine/backtest/strategies/momentum.py        → base.py
engine/backtest/strategies/ma_crossover.py    → base.py
engine/backtest/strategies/rsi_reversion.py   → base.py
engine/backtest/strategies/mean_reversion.py  → base.py
engine/backtest/strategies/trend_following.py → base.py
engine/backtest/strategies/breakout.py        → base.py
engine/backtest/strategies/volatility.py      → base.py
engine/backtest/strategies/funding_arb.py     → base.py
engine/backtest/strategies/combined.py        → base.py (multi-factor combinations)
```

### Social + TradFi data

```
engine/social/config.py
engine/social/collectors/base.py         Abstract collector
engine/social/collectors/farcaster.py    → base.py
engine/social/collectors/fear_greed.py   → base.py
engine/social/collectors/polymarket.py   → base.py
engine/social/collectors/reddit.py       → base.py
engine/social/collectors/telegram.py     → base.py
engine/social/collectors/tiktok.py       → base.py
engine/social/collectors/trends.py       → base.py
engine/social/extractors/entity.py
engine/social/extractors/llm_analyzer.py
engine/social/filters/echo_chamber.py
engine/social/filters/preprocessing.py
engine/social/scoring/aggregator.py
engine/social/scoring/contrarian.py
engine/social/scoring/divergence.py
engine/social/scoring/influencer.py
engine/social/scoring/temporal.py

engine/tradfi/fred.py         FRED macro data (rates, spreads)
engine/tradfi/yahoo.py        Equity OHLCV + fundamentals
engine/tradfi/sec_edgar.py    Insider filings (Form 4, 13F)
engine/tradfi/openinsider.py  Insider trade aggregation
```

---

## Layer 4 — Brain + Backtest Engine

Synthesis, regime detection, learning. Depends on Layers 0–3.

### Brain

```
engine/brain/signal_normalizer.py  → producers/base.py (asset-aware normalization)
engine/brain/regime.py             → database.py, models.py
engine/brain/synthesis.py          ⇒ database.py, scoring.py, regime.py
engine/brain/conviction.py         → synthesis.py, regime.py
engine/brain/kill_switch.py        → database.py, models.py
engine/brain/feature_store.py      → database.py (frozen feature snapshots per cycle)
engine/brain/data_quality.py       → database.py, feature_store.py
engine/brain/learning.py           → database.py, scoring.py
engine/brain/decision.py           → synthesis.py, conviction.py, kill_switch.py
engine/brain/hooks.py              → database.py (extension hooks)
engine/brain/orchestrator.py       ⇒ synthesis.py, kill_switch.py, feature_store.py, decision.py
engine/brain/pcs_enricher.py       → database.py, feature_store.py
engine/brain/position_sm.py        → models.py (position state machine)
```

> **Note**: Feature snapshots are currently write-only (audit trail). FeatureStore replay is not yet implemented.

### Backtest engine

```
engine/backtest/engine.py       ⇒ strategies/, simulator.py, stats.py
engine/backtest/simulator.py    → strategies/base.py
engine/backtest/walkforward.py  → engine.py, validation.py
engine/backtest/sweep.py        → engine.py, validation.py (parameter grid sweep)
engine/backtest/regime.py       → engine.py, brain/regime.py
engine/backtest/stats.py        → (scipy, pandas — no internal deps)
engine/backtest/validation.py   → stats.py (FDR correction, OOS splits)
engine/backtest/io.py           → database.py (data loading)
```

### Social pipeline

```
engine/social/pipeline.py  ⇒ collectors/, extractors/, filters/, scoring/
```

---

## Layer 5 — Execution + Integration

Order management, karma, integrations. Depends on Layers 0–4.

### Execution

```
engine/execution/position_sizer.py  → brain/conviction.py
engine/execution/dynamic_kelly.py   → database.py, execution/pnl.py
engine/execution/policy.py          → brain/kill_switch.py, core/policy.py
engine/execution/preflight.py       → policy.py, core/config.py
engine/execution/oms.py             ⇒ policy.py, preflight.py, database.py
engine/execution/paper.py           → oms.py
engine/execution/hyperliquid.py     → oms.py, core/config.py
engine/execution/pnl.py             → database.py, models.py
engine/execution/karma.py           → database.py, core/contributors.py
engine/execution/karma_governance.py→ karma.py
engine/execution/circuit_breaker.py → brain/kill_switch.py, database.py
```

### Integration layer

```
engine/integration/hooks.py          → database.py, brain/hooks.py
engine/integration/learning_loop.py  ⇒ brain/learning.py, execution/karma.py
engine/integration/outcome_writer.py → database.py, execution/pnl.py
engine/integration/pattern_matcher.py→ database.py
engine/integration/thesis_bridge.py  → database.py, brain/conviction.py
```

### External integrations

```
engine/integrations/forge.py           (standalone — no internal deps)
engine/integrations/eas.py             → core/config.py, integrations/eas_schema.py
engine/integrations/eas_schema.py      (standalone)
engine/integrations/github_publish.py  → core/config.py, core/contributors.py
```

### Oracle primitives

```
engine/core/provenance.py        ⇒ database.py, execution/karma.py
engine/core/oracle_query_log.py  (standalone — no internal deps)
```

---

## Layer 6 — Interface Layer

API, dashboard, CLI. Depends on all layers below. This layer is the only layer that external callers interact with directly.

### REST API

```
api/auth.py                  Token validation middleware
api/auth_kill_switch.py      Kill-switch-aware auth dependency
api/deps.py                  FastAPI dependency providers (get_db, get_config, …)
api/errors.py                Structured error format
api/schemas/                 Pydantic request/response schemas
api/routes/brain.py          → brain/orchestrator.py
api/routes/config.py         → core/config.py
api/routes/contributors.py   → core/contributors.py, core/scoring.py
api/routes/events.py         → core/database.py              (SSE stream)
api/routes/health.py         (standalone)
api/routes/karma.py          → execution/karma.py, execution/karma_governance.py
api/routes/kill_switch.py    → brain/kill_switch.py
api/routes/mcp.py            → core/database.py, core/provenance.py  (MCP server)
api/routes/oracle.py         → core/provenance.py, core/oracle_query_log.py  (public, no auth)
api/routes/positions.py      → execution/pnl.py, execution/oms.py
api/routes/producers.py      → producers/registry.py
api/routes/producers_feedback.py → core/database.py
api/routes/regime.py         → brain/regime.py
api/routes/signals.py        → core/ingestion.py, core/contributors.py
api/routes/trace.py          → core/database.py              (trace sessions)
api/routes/__init__.py       → api/routes/*
api/main.py                  ⇒ api/routes/__init__.py, core/config.py
```

### CLI

```
engine/cli/commands/anchor.py  → core/database.py, integrations/eas.py
engine/cli/commands/export.py  ⇒ core/database.py, execution/karma.py
engine/cli/main.py             ⇒ all commands, core/config.py
engine/cli/__main__.py         → cli/main.py
engine/cli_keys.py             → security/keystore.py
```

---

## One-writer rule

The event store is append-only and single-writer by design. Do not run multiple processes with write access to the same `brain.db`.

Safe concurrent readers: dashboard, oracle endpoint, CLI reads, monitoring.

See `docs/security.md` for enforcement details.

---

## Adding a module

1. Determine its layer (what does it depend on? what depends on it?)
2. Add to LAYERS in `scripts/validate_code_deps.py`
3. Add to this document under the correct layer section
4. Run `python scripts/validate_code_deps.py` — must pass before merging

---

---

---

---

---

---

---

---

## Undocumented (auto-detected)

> Modules detected by CI but not yet assigned to a layer. Move each entry to the correct layer section and add a description.

```
api/routes/metrics.py
engine/cli/commands/wizard.py
engine/execution/recovery.py
```
