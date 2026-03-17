# FLYWHEEL SPRINT PLAN
## Close the loop. Make money. Prove it compounds.

> **Created:** 2026-02-28  
> **Status:** Planning  
> **Goal:** Close the signal → trade → outcome → attribution loop so b1e55ed earns its name.

---

## The Actual Problem

The codebase has:
- Producers emitting domain features (TradFiSignalPayload, TASignalPayload, etc.)
- Synthesis converting features → 0–1 weighted score
- Conviction converting score → direction + magnitude
- Decision converting conviction → TradeIntent
- OMS executing TradeIntent → paper fill
- P&L tracking unrealized/realized

**What's broken:**
1. When a position closes, nothing looks back and says "which signals contributed to this trade"
2. KarmaEngine exists but `attribute_outcome()` is never called
3. No per-producer direction/confidence output — producers emit raw metrics, not actionable calls
4. No cockpit — the brain's top conviction call lives only in the DB
5. No benchmark comparison — impossible to know if the brain adds edge
6. Kill switches exist but not all spec conditions are wired (consecutive losses, fill divergence)
7. TradFi producer needs external endpoint that doesn't exist

One sentence: **the pipes are all there; none of them connect end-to-end.**

---

## Attribution Algorithm v1 (WRITE THIS DOWN BEFORE BUILDING)

> Must be immutable before any contributor joins. Cannot retroactively attribute.

```
When a position closes with realized P&L:

1. Retrieve all SIGNAL_ACCEPTED_V1 events linked to this trade_id
   - These were emitted when synthesis consumed a domain signal into a conviction
   - Each event carries: producer_id, domain, signal_event_id, contribution_weight

2. Phase 0: equal weights across all contributing producers
   (Track marginal contribution data, but do not apply it yet)

3. Outcome mapping:
   P&L > 0  → outcome = +1.0 (positive)
   P&L < 0  → outcome = -1.0 (negative — tracked only, not penalized in Phase 0)
   P&L ≈ 0  → outcome = 0.0

4. Karma update (EMA, α = 0.05):
   karma_new = karma_old * 0.95 + outcome * 0.05
   (Phase 0: apply positive updates only; negative stored for analysis, not applied)

5. Emit ATTRIBUTION_OUTCOME_V1 event:
   {trade_id, realized_pnl_usd, contributing_producers: [{producer_id, weight, outcome}]}

Karma score starts at 1.0 for all producers (Phase 0 neutral).
Confidence stratification tags: high = confidence > 0.65, low = confidence < 0.45.
30-day proof: do high-confidence signals outperform low-confidence after fees?
```

---

## Kill Switch Spec (5 conditions, all must be wired)

| Condition | Trigger | Action | Level |
|-----------|---------|--------|-------|
| Consecutive losses | 3 in a row | Pause signal generation, notify | DEFENSIVE |
| Single loss | > 2% portfolio | Auto-close position | DEFENSIVE |
| Total open risk | > 5% portfolio | Block new positions in preflight | CAUTION |
| Data feed degraded | Any producer fails > 2 cycles | Flatten all signals to neutral | CAUTION |
| Fill divergence | Actual fill > 0.5% from intended | Pause, investigate | CAUTION |

---

## 30-Day Proof Metric

**PRIMARY:** Confidence stratification test  
Do signals with confidence > 0.65 outperform signals with confidence < 0.45 after fees?  
This proves weighting works. P&L at n<50 trades is noise.

**SECONDARY (monitoring only):** Sortino > 1.5 — not a gate, just a watch

**Benchmarks (always running, never optional):**
1. Naive momentum — buy above 20MA, sell below
2. Equal-weight ensemble — average all producer signals
3. Flat/no-trade — zero exposure (catches overtrading)
4. Discretionary — zoz's manual override when applicable

Brain must beat ALL FOUR to claim edge.

---

## Scope Lock (Phase 0, non-negotiable)

```
Assets:   BTC, ETH, SOL
Venue:    Hyperliquid only
Horizon:  Intraday swing
Risk:     1% portfolio max per trade
Mode:     Paper trading first; live only when cockpit looks right for 2+ weeks
```

---

## Branch Strategy

```
develop
└── feat/flywheel          ← main integration branch
    ├── flywheel/s0-spec   ← spec + schema (no logic)
    ├── flywheel/s1-attribution-layer
    ├── flywheel/s2-karma-wiring
    ├── flywheel/s3-smart-tradfi
    ├── flywheel/s4-benchmarks
    ├── flywheel/s5-kill-switches
    ├── flywheel/s6-cockpit
    └── flywheel/s7-paper-loop
```

**Rules:**
- All sprint branches cut from `feat/flywheel`, not from `develop`
- All sprint PRs target `feat/flywheel`
- Squash-merge each sprint PR (clean history)
- `feat/flywheel` → `develop` only when S7 is complete and Phase 0 loop is proven
- No individual sprint branch ever touches `develop` directly
- CI must pass on every sprint PR before merge

---

## Sprint Breakdown

---

### S0 — Spec & Schema Foundation
**Branch:** `flywheel/s0-spec`  
**Estimate:** 1 day  
**Goal:** Written spec + new event types + signal contract. No logic changes.

**Deliverables:**
- `docs/FLYWHEEL_SPEC.md` — this document, committed to repo
- `engine/core/events.py`:
  - Add `EventType.ATTRIBUTION_OUTCOME_V1 = "attribution.outcome.v1"`
  - Add `AttributionOutcomePayload(BaseModel)` with fields: `trade_id`, `realized_pnl_usd`, `producers: list[ProducerOutcome]`, `confidence_bucket` (high/mid/low)
  - Add `SignalAcceptedPayload(BaseModel)`: `trade_id`, `producer_id`, `domain`, `signal_event_id`, `contribution_weight`, `direction`, `confidence`
- `engine/core/types.py`:
  - Add `horizon: str | None` and `invalidation: float | None` to `ConvictionScore`
  - Add `horizon: str | None` and `invalidation: float | None` to `TradeIntent`
- `engine/api/routes/signals.py` (new):
  - `POST /api/v1/signals/validate` — validates a producer payload against schema, returns pass/fail + errors; **no recording**

**Acceptance criteria:**
- All existing tests still pass
- New event types appear in `_EVENT_PAYLOAD_MODELS` map
- Validate endpoint returns 200 + `{"valid": true}` for a valid tradfi payload
- Validate endpoint returns 422 + error list for invalid payload

---

### S1 — Signal Attribution Layer
**Branch:** `flywheel/s1-attribution-layer`  
**Estimate:** 2 days  
**Goal:** When synthesis consumes a domain signal into a conviction, emit a receipt. When OMS fires, link the trade to those receipts.

**The gap:** Right now synthesis reads domain events silently — no record of which event_ids contributed to which TradeIntent. Attribution is impossible without this.

**Deliverables:**
- `engine/brain/synthesis.py`:
  - When synthesis reads a domain signal event, collect the event_id
  - Add `source_event_ids` to `SynthesisResult` (field already exists on `FeatureSnapshot` — wire it through)
- `engine/brain/conviction.py`:
  - When emitting `CONVICTION_V1` event, include `source_event_ids` in payload
- `engine/execution/oms.py`:
  - After placing an order, emit `SIGNAL_ACCEPTED_V1` events — one per contributing domain signal
  - Each `SignalAcceptedPayload`: `trade_id=order_id`, `producer_id=source`, `domain=domain`, `signal_event_id=event_id`, `contribution_weight=1.0 (Phase 0)`, `direction=conviction.direction`, `confidence=conviction.confidence`
- `engine/core/events.py`:
  - Add `CONVICTION_V1 = "brain.conviction.v1"` if not present (check first)
  - Add `confidence_bucket` computed property to `SignalAcceptedPayload`

**Acceptance criteria:**
- After a paper trade executes, `SIGNAL_ACCEPTED_V1` events exist in DB for that trade_id
- Events contain at least one contributing domain signal per trade
- All existing 583+ tests still pass
- New unit tests: `test_signal_accepted_emitted_on_trade`, `test_source_event_ids_propagated`

---

### S2 — Karma Attribution Wiring
**Branch:** `flywheel/s2-karma-wiring`  
**Estimate:** 2 days  
**Goal:** Position close → karma update. The flywheel's crank.

**The gap:** `KarmaEngine.record_intent()` exists. `PnLTracker.unrealized_usd()` exists. But close → attribution → karma is not wired.

**Deliverables:**
- `engine/execution/pnl.py`:
  - Add `close_position(position_id, exit_price, now_fn=None) -> PnLSnapshot` method
  - Updates positions table: status='closed', exit_price, realized_pnl
  - Returns PnLSnapshot with realized_usd
- `engine/execution/karma.py`:
  - Add `attribute_outcome(trade_id, realized_pnl_usd, db) -> AttributionResult` method
  - Queries `SIGNAL_ACCEPTED_V1` events for this trade_id
  - Computes karma update per producer (Phase 0: equal weight, positive-only EMA)
  - Upserts `producer_karma` table: `{producer_id, karma_score, win_count, loss_count, last_updated}`
  - Emits `ATTRIBUTION_OUTCOME_V1` event
- DB migration:
  - New table: `producer_karma (producer_id TEXT PRIMARY KEY, karma_score REAL DEFAULT 1.0, win_count INT DEFAULT 0, loss_count INT DEFAULT 0, last_updated TEXT)`
- `engine/execution/oms.py`:
  - After position close confirmation from broker: call `pnl.close_position()` then `karma.attribute_outcome()`
  - Non-blocking: karma failure must never break execution (wrap in try/except, log)
- `engine/brain/synthesis.py`:
  - Load producer karma weights from `producer_karma` table when available
  - Fall back to 1.0 (Phase 0 neutral) if table empty

**Acceptance criteria:**
- End-to-end test: paper trade opened → closed → karma table updated
- `producer_karma` table persists across process restarts
- `ATTRIBUTION_OUTCOME_V1` event emitted with correct trade_id
- karma_score updates correctly for positive and negative outcomes
- karma failure does not crash or block execution
- New tests: `test_close_position_emits_karma`, `test_karma_attribution_equal_weight`, `test_karma_failure_nonblocking`

---

### S3 — Smart TradFi Producer
**Branch:** `flywheel/s3-smart-tradfi`  
**Estimate:** 2 days  
**Goal:** Self-contained tradfi signal. No external endpoint. Calls Binance directly. Outputs direction + confidence.

**The gap:** `TradFiBasisProducer` calls `B1E55ED_TRADFI_BASIS_URL` which doesn't exist. It's a shell with no data source.

**Deliverables:**
- `engine/producers/tradfi.py`:
  - Replace HTTP endpoint dependency with direct Binance API calls:
    - Spot price: `GET https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT`
    - Quarterly futures: `GET https://dapi.binance.com/dapi/v1/ticker/price?symbol=BTCUSD_YYMMDD`
    - Perpetual funding rate: `GET https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=1`
    - Open interest: `GET https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT`
  - Compute basis_annualized, funding_annualized, oi_change_pct internally
  - Add rule-based signal synthesis:
    ```
    if basis < 3% and funding < 0:   direction=short, confidence=0.65
    if basis 3-6% and funding 5-20%: direction=long,  confidence=0.55 (healthy)
    if basis > 8%:                   direction=short, confidence=0.60 (crowded, unwind risk)
    if meltup_score == 4:            direction=long,  confidence=0.75
    ```
  - Add `direction: str | None` and `confidence: float | None` to `TradFiSignalPayload`
  - Add `horizon: str = "swing"` and `invalidation: float | None` to `TradFiSignalPayload`
- No LLM in this sprint — pure rule-based. LLM curator is a future sprint.
- `B1E55ED_TRADFI_BASIS_URL` env var → deprecated (still supported for backward compat)

**Acceptance criteria:**
- Producer runs without any env vars set (self-contained)
- Emits signals with direction + confidence for BTC, ETH, SOL
- Binance API calls mocked in unit tests
- Rules produce correct direction for each basis/funding scenario
- New tests: `test_tradfi_self_contained`, `test_tradfi_direction_rules`, `test_tradfi_no_external_endpoint_required`

---

### S4 — Benchmark Signals
**Branch:** `flywheel/s4-benchmarks`  
**Estimate:** 1.5 days  
**Goal:** 4 baseline signals always running in the same pipeline as real signals.

**Why this is critical:** Without benchmarks running from Day 1, you cannot measure if the brain adds edge at Day 30.

**Deliverables:**
- `engine/producers/benchmarks.py` (new file):
  - `BenchmarkMomentumProducer`: fetches price from DB or Binance; long if price > 20-period EMA, short if below; confidence = 0.50 (flat); emits `SIGNAL_TA_V1` with `source="benchmark.momentum"`
  - `BenchmarkFlatProducer`: always emits flat/neutral at confidence = 0.0; emits with `source="benchmark.flat"`
  - `BenchmarkEqualWeightProducer`: averages direction of all other active signals; emits with `source="benchmark.equal_weight"`
  - `BenchmarkDiscretionaryProducer`: reads from a `discretionary_signals` table (operator-injected via API); emits with `source="benchmark.discretionary"`. Empty table = no signal.
- All 4 registered in producer registry with `domain="benchmark"`
- `engine/api/routes/cockpit.py`:
  - `POST /api/v1/benchmarks/discretionary` — operator posts manual signal `{symbol, direction, confidence, reasoning}` for discretionary benchmark
- Attribution pipeline: benchmark signals flow through the same `SIGNAL_ACCEPTED_V1` → karma path as real signals. They get karma scores too. Karma for benchmarks is how you quantify "brain adds X% vs naive momentum."

**Acceptance criteria:**
- All 4 benchmarks produce signals for BTC/ETH/SOL on each cycle
- Benchmark signals appear in DB alongside real signals
- Discretionary endpoint accepts and persists manual override
- Benchmarks do NOT affect kill switch state
- New tests: `test_momentum_benchmark_direction`, `test_flat_benchmark_always_neutral`, `test_equal_weight_averages_actives`

---

### S5 — Kill Switch Hardening
**Branch:** `flywheel/s5-kill-switches`  
**Estimate:** 1 day  
**Goal:** All 5 kill switch conditions from spec are enforced, not just structural.

**Audit of current state:**
- KillSwitch struct + persistence: ✅ exists
- DEFENSIVE → no new positions: ✅ in `DefaultDecisionPolicy`
- Consecutive loss tracking: ❓ check if `learning.py` tracks this
- Single loss >2% → auto-close: ❓ likely not wired
- Total open risk >5%: partially wired in `PositionSizer`
- Data feed degraded: ❓ likely not wired to signal flattening
- Fill divergence check: ❓ not found in OMS

**Deliverables:**
- `engine/execution/oms.py`:
  - After fill confirmation: compare intended_price vs actual_fill_price; if divergence > 0.5%: trigger CAUTION + emit audit event + notify
  - Add `_check_fill_divergence(intended, actual) -> bool`
- `engine/brain/learning.py` (or `kill_switch.py`):
  - Track consecutive loss count in DB (`kill_switch_state` table or `system_state`)
  - After each position close with P&L < 0: increment; on 3rd → escalate to DEFENSIVE; reset on any win
- `engine/execution/preflight.py`:
  - Add check: total_open_risk_pct > 5% → reject with reason="risk_limit_open_risk"
- `engine/brain/orchestrator.py` (or signal pipeline):
  - Add data quality check: if any domain has 0 events in last 2 cycles → flatten that domain's contribution to 0.5 (neutral)
  - If all domains degraded → set kill_level = CAUTION
- `engine/execution/oms.py`:
  - After realized P&L > -2% of portfolio value: trigger auto-close on remaining position, notify

**Acceptance criteria:**
- 3 consecutive paper losses → kill_level escalates to DEFENSIVE
- Single position loss > 2% → position auto-closed
- Total open risk > 5% → new OMS order rejected
- Data feed with 0 events → domain flattened to neutral
- Fill divergence > 0.5% → audit event emitted + CAUTION triggered
- New tests: all 5 conditions covered

---

### S6 — Cockpit Dashboard
**Branch:** `flywheel/s6-cockpit`  
**Estimate:** 2 days  
**Goal:** Single-screen "what do I trade today" view.

**Design principle:** Brutally utilitarian. No storytelling. This is a trading tool, not a showcase.

**Deliverables:**
- `engine/api/routes/cockpit.py`:
  - `GET /cockpit` → renders cockpit template
  - `GET /api/v1/cockpit/state` → JSON: `{top_call, producer_signals, benchmark_comparison, kill_switch_level, open_positions}`
  - `top_call`: `{asset, direction, confidence, horizon, invalidation, size_pct, entry_approx}`
  - `producer_signals`: list of `{producer_id, domain, direction, confidence, karma_score}` — sorted by confidence
  - `benchmark_comparison`: `{momentum_direction, flat_pnl_7d, brain_pnl_7d, equal_weight_pnl_7d}`
  - `kill_switch_level`: current level + reason
  - `open_positions`: list from DB
- `engine/templates/cockpit.html`:
  - HTMX auto-refresh every 30s
  - Top section: TOP CALL — asset, L/S/F, confidence bar, horizon, invalidation price, recommended size
  - Middle section: Producer breakdown — table of producers + direction + confidence + karma score + agree/disagree with top call
  - Bottom left: Benchmark comparison — 7d P&L per signal source
  - Bottom right: Kill switch status + consecutive loss counter + open risk %
  - Confidence stratification row: "High confidence signals (>0.65): N signals, P&L avg: +$X | Low (<0.45): N signals, P&L avg: -$Y"
- Tailwind CSS, dark mode, minimal (existing dashboard style)

**Acceptance criteria:**
- `/cockpit` loads in browser in < 1s
- Auto-refreshes without page reload
- Shows correct kill switch level
- Displays all 4 benchmark signals
- Disagreement map correctly shows which producers disagree with top call
- New test: `test_cockpit_state_endpoint_schema`

---

### S7 — Paper Loop Closure + Stratification Tracking
**Branch:** `flywheel/s7-paper-loop`  
**Estimate:** 2 days  
**Goal:** The loop is closed. From this day forward, every signal is tracked, every outcome is attributed, the stratification data accumulates.

**Deliverables:**
- `engine/brain/orchestrator.py`:
  - When top conviction signal has confidence > 0.65 AND kill_level == SAFE: auto-submit to paper broker
  - When confidence 0.45–0.65: log to cockpit but do NOT auto-execute (require manual confirm)
  - When confidence < 0.45: log as low-conviction, no action
- `engine/execution/paper.py`:
  - Ensure paper positions persist through process restarts
  - Add `get_open_positions() -> list[PaperPosition]` (probably already exists — wire to cockpit)
- `engine/brain/learning.py`:
  - Add `StratificationTracker` class
  - On each signal emitted: classify as high (>0.65) / mid (0.45–0.65) / low (<0.45)
  - On each outcome: update stratification bucket running stats
  - Methods: `get_stratification_report() -> dict` with realized P&L per bucket, signal count, avg confidence
- `engine/cli/commands/report.py`:
  - `b1e55ed report --stratification` — prints stratification table to stdout
  - `b1e55ed report --cockpit-summary` — 7-day summary suitable for daily review
- DB migration:
  - New table: `signal_stratification (signal_id TEXT, confidence REAL, bucket TEXT, outcome REAL | NULL, attributed_at TEXT | NULL)`

**Acceptance criteria:**
- Confidence >0.65 signal → automatically paper-traded → position in DB → fills karma on close
- `b1e55ed report --stratification` produces a table with 3 rows (high/mid/low)
- Stratification data survives process restart
- After 5 paper trades: `producer_karma` table has non-1.0 entries
- New tests: `test_auto_paper_on_high_confidence`, `test_stratification_buckets`, `test_report_stratification_cli`

---

## Execution Notes

### Codex Spawn Protocol (for each sprint)

```python
sessions_spawn(
    task="<sprint task>",
    model="openai-codex/gpt-5.3-codex",
    thinking="xhigh",
    cleanup="keep"
)
```

**Every Codex task footer must include:**
```
After writing each file:
  cat <file>

After all files:
  cd /home/ubuntu/b1e55ed
  git add -A && git commit -m "feat(flywheel): <sprint summary>"
  python -m pytest tests/ -x -q 2>&1 | tail -20
  
Print summary: what changed, how to verify, test count before/after.
```

### Sprint Dependencies

```
S0 ──► S1 ──► S2 ──► (S3, S4, S5 in parallel) ──► S6 ──► S7
```

S3/S4/S5 can run in parallel after S2 merges into `feat/flywheel`.

### What is NOT in Phase 0

- External operator onboarding
- Token / USDC rewards / karma economics
- ZK proofs for attribution privacy
- Public leaderboard or API
- Smart producers beyond tradfi (onchain, sentiment, technical, macro → Phase 0.5)
- MCP server / external discovery

---

## Phase 0 Complete When

1. ✅ S7 merged to `feat/flywheel`
2. ✅ At least 20 paper trades completed
3. ✅ `b1e55ed report --stratification` shows high-confidence signals outperforming low-confidence
4. ✅ All 4 benchmarks running for 14+ days
5. ✅ Cockpit has been reviewed daily for 1 week without issues
6. ✅ `feat/flywheel` → `develop` PR opened and reviewed by zoz

At that point: zoz decides whether to go live with real capital.

---

## Smart Producers (Phase 0.5 — After Loop Is Proven)

These are queued. Do not build until S7 is complete.

| Producer | Data Sources | Key Signal |
|----------|-------------|-----------|
| smart-onchain | Nansen netflows + Allium wallet clusters | Smart money accumulation/distribution |
| smart-sentiment | F&G index + CT velocity + divergence detection | Contrarian setup detection |
| smart-technical | Multi-TF TA + Wyckoff phase detection | Structure + momentum alignment |
| smart-macro | ETF flows + DXY + yields + SOFR | Risk-on/risk-off regime state |

Each will follow same pattern as smart-tradfi: self-contained data collection + rule synthesis + optional LLM curator.

---

*"It now looks like a system designed to discover whether it actually has edge — rather than a system designed to look impressive."*

*That's the whole thing. Start Monday.*
