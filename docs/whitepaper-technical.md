# b1e55ed: A Falsifiable Profit Engine for Systematic Crypto Trading

**Version**: 1.0.0-beta.8 | **Date**: March 2026

---

## Abstract

Most crypto "alpha" is unverifiable. Signal services give you a call with no prior calibration, no track record, no accountability. Discretionary traders cannot separate skill from luck. Even systematic traders rarely close the attribution loop — they know the P&L but not which signals drove which trades, which producers were right, or whether their confidence calibration reflects reality.

b1e55ed is a **falsifiable profit engine** designed to close that loop. Every forecast is an immutable, timestamped probability statement attributed to a specific producer. Every outcome is resolved against actual prices. Every score feeds back into weights and confidence calibration. The system cannot retroactively explain away losses because the evidence chain is hash-linked and externally verifiable.

The benchmark is not beating a market index — it's beating flat/no-trade. The system must prove it earns its execution cost. Four benchmarks run in parallel (naive momentum, equal-weight ensemble, flat/no-trade, discretionary override), and the brain must outperform all four to claim edge. The primary proof metric is confidence stratification: do signals with confidence > 0.65 outperform signals with confidence < 0.45 after fees?

The current implementation (beta.8) runs 13 domain producers through a 7-layer interpreter stack, resolves outcomes every 30 minutes via Brier score, and updates producer karma via EMA. All adaptive layers default to shadow mode — they observe and log without mutating forecasts. The meta-producer activates only after 500 resolved outcomes accumulate. This is deliberate: the system must prove its calibration before it earns trust.

---

## 1. Problem Statement

### 1.1 The Alpha Accountability Gap

The crypto signal industry operates without accountability. A typical pattern:

1. Signal provider issues a call: "Long BTC at $65k, target $70k"
2. Price moves. Sometimes up, sometimes down.
3. If up: the call is celebrated. If down: the call is memory-holed or blamed on "market conditions."
4. No record of prior confidence. No denominator of total calls. No Brier score. No calibration curve.

This is not alpha discovery. It is survivorship bias with extra steps.

The problem extends beyond signal services. Discretionary traders face the same attribution gap: they know their P&L but not which intuitions drove which trades. Systematic traders with backtested strategies often discover that live performance diverges from historical expectations — and have no mechanism to isolate which component degraded.

### 1.2 Why Existing Systems Fail

Existing systematic trading frameworks fail at different points in the accountability chain:

**No forecast immutability.** Most systems allow post-hoc modification of signals. A forecast that can be edited after emission is not a forecast — it is a narrative.

**No confidence calibration.** Systems that emit buy/sell signals without confidence weights cannot be scored for calibration. Binary signals are scientifically useless at small sample sizes.

**No attribution granularity.** Multi-factor systems that produce a single blended signal cannot identify which factors contributed to which outcomes. The feedback loop has no gradient.

**No benchmark discipline.** Systems that compare themselves only to market indices cannot distinguish "alpha" from "levered beta." The relevant question is not "did you beat the index?" but "did you beat doing nothing?"

**No kill switch rigor.** Systems without explicit failure conditions will trade through drawdowns that should trigger review. The absence of defined failure is the presence of undefined failure.

### 1.3 Requirements for a Falsifiable System

A falsifiable profit engine must satisfy:

1. **Forecast immutability.** Every forecast is timestamped and hash-linked. No retroactive modification.

2. **Confidence calibration.** Every forecast includes a probability estimate. Outcomes are scored against stated confidence (Brier score).

3. **Attribution granularity.** Every trade is linked to contributing signals. Every signal is attributed to a specific producer. Karma flows to producers, not to the system abstractly.

4. **Benchmark discipline.** Multiple baselines run in parallel. The system must beat all of them to claim edge.

5. **Kill switch conditions.** Explicit failure conditions trigger defensive postures. The system admits when it is broken.

6. **External verifiability.** A third party with no system access can verify the claim chain via the oracle endpoint.

---

## 2. System Architecture

### 2.1 Event-Sourced Core

b1e55ed is built on event sourcing. All state changes are represented as immutable events in a hash-linked chain. The primary event types:

| Event Type | Description |
|------------|-------------|
| `SIGNAL_*.V1` | Raw domain signal (tradfi, onchain, technical, social, events, curator) |
| `FORECAST_V1` | Producer forecast with action, confidence, horizon |
| `FORECAST_OUTCOME_V1` | Resolved outcome with Brier score |
| `CONVICTION_V1` | Brain synthesis output |
| `SIGNAL_ACCEPTED_V1` | Attribution link: signal → trade |
| `ATTRIBUTION_OUTCOME_V1` | Karma attribution: trade → producers |

The event store is SQLite with deterministic hash chaining. Each event includes `prev_hash`, creating a Merkle-like structure that detects tampering. The `verify_hash_chain()` function validates chain integrity.

### 2.2 The Producer Layer (13 Base Producers)

Producers are signal generators that feed the brain's synthesis engine. Each producer periodically collects data, normalizes it into a typed payload, and publishes events. The 13 base producers span 6 domains:

| Domain | Producers | What They Signal |
|--------|-----------|------------------|
| **curator** | `curator-intel`, `ai-consensus` | Operator thesis, LLM ensemble consensus |
| **onchain** | `onchain-flows`, `stablecoin-supply`, `whale-tracking` | Whale netflow, liquidity cycles, smart money positioning |
| **tradfi** | `tradfi-basis`, `etf-flows` | Basis/funding regimes, ETF flow pressure |
| **social** | `social-intel`, `market-sentiment` | Narrative ignition, fear/greed, contrarian flags |
| **technical** | `technical-analysis`, `orderbook-depth`, `price-alerts` | Structure, imbalance, microstructure |
| **events** | `market-events`, `meta` | Catalysts, ensemble pattern matching |

Producers are dumb signal emitters by design. They collect data, normalize it, and publish. They have no memory of whether they were right or wrong, no awareness of what other producers are saying, and no ability to adapt to different market regimes. That intelligence lives in the interpreter stack.

### 2.3 The Interpreter Stack (P3/P4 — 7 Layers)

Every producer's raw output passes through a layered interpreter chain before becoming a `FORECAST_V1` event. The stack is applied automatically by `BaseProducer.emit_forecast()`:

```
┌─────────────────────────────────────────────────────────┐
│                   NoveltyInterpreter                    │  ← P4.3: cross-producer awareness
│  ┌───────────────────────────────────────────────────┐  │
│  │              ProsecutorInterpreter                │  │  ← P3.5: adversarial counter-case
│  │  ┌─────────────────────────────────────────────┐  │  │
│  │  │           SelfMemoryInterpreter             │  │  │  ← P3.4: karma-based confidence
│  │  │  ┌───────────────────────────────────────┐  │  │  │
│  │  │  │         RegimeInterpreter             │  │  │  │  ← P3.2: regime conditioning
│  │  │  │  ┌─────────────────────────────────┐  │  │  │  │
│  │  │  │  │      LLMCriticInterpreter       │  │  │  │  │  ← P3.1: LLM shadow critique
│  │  │  │  │  ┌───────────────────────────┐  │  │  │  │  │
│  │  │  │  │  │   Interpreter (base)      │  │  │  │  │  │  ← rule-based interpret()
│  │  │  │  │  │  ┌─────────────────────┐  │  │  │  │  │  │
│  │  │  │  │  │  │   BaseProducer      │  │  │  │  │  │  │  ← raw signal collection
│  │  │  │  │  │  └─────────────────────┘  │  │  │  │  │  │
│  │  │  │  │  └───────────────────────────┘  │  │  │  │  │
│  │  │  │  └─────────────────────────────────┘  │  │  │  │
│  │  │  └───────────────────────────────────────┘  │  │  │
│  │  └─────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                         ↓
                   FORECAST_V1 event
```

**Key invariant:** No layer in the stack ever changes the forecast `action` (long/short/flat). Only `confidence` is modulated, or the forecast is replaced with an abstention.

### 2.4 Brain Synthesis and Conviction

The brain reads `FORECAST_V1` events and synthesizes them into a conviction score. Synthesis uses domain weights (configurable, default sum to 1.0):

| Domain | Default Weight |
|--------|----------------|
| curator | 0.25 |
| onchain | 0.25 |
| tradfi | 0.20 |
| social | 0.15 |
| technical | 0.10 |
| events | 0.05 |

Domain weights are modulated by the hierarchy engine (P4.1) based on rolling Brier scores. The conviction engine converts the weighted score into a direction (long/short/flat) and magnitude (0-100 PCS — Position Conviction Score).

### 2.5 Execution and Kill Switches

Execution follows conviction through a preflight check, then submits to paper or live broker. Five kill switch conditions are enforced:

| Condition | Trigger | Action | Level |
|-----------|---------|--------|-------|
| Consecutive losses | 3 in a row | Pause signal generation, notify | DEFENSIVE |
| Single loss | > 2% portfolio | Auto-close position | DEFENSIVE |
| Total open risk | > 5% portfolio | Block new positions in preflight | CAUTION |
| Data feed degraded | Any producer fails > 2 cycles | Flatten domain signals to neutral | CAUTION |
| Fill divergence | Actual fill > 0.5% from intended | Pause, investigate | CAUTION |

Kill switches are not suggestions. They are hard gates that override conviction.

### 2.6 The Oracle and Contributor Network

The oracle is a read-only projection layer over the event store. It answers one question: does this signal producer have verifiable history? No authentication required.

**Oracle endpoint:** `GET /api/v1/oracle/producers/{id}/provenance`

Returns:
- `chain_verified`: whether the hash chain validates
- `total_forecasts`: count of attributed forecasts
- `resolved_forecasts`: count with outcomes
- `brier_score`: aggregate calibration metric
- `karma_score`: 5-factor composite reputation

External agents can query the oracle to verify claims before trusting a contributor's signals.

---

## 3. The Intelligence Layer

### 3.1 P3: Per-Signal Adaptations

P3 layers wrap individual producer outputs. They add intelligence at the signal level.

#### 3.1.1 LLM Critic (shadow-first)

An LLM reviews the rule-engine's candidate forecast and flags mis-calibrated confidence or signals that should be suppressed.

**Input:** Candidate `ForecastPayload`, top 5 raw signals, regime tag, trailing Brier score, aggregate conviction.

**Output:** `confidence_delta` (±0.3 max), optionally `suppress=True`.

**Shadow mode** (default): Critique is computed and stored but does not affect output. Logged to `llm_shadow_log` table for later analysis.

**Meta-guardrail:** If the producer's trailing Brier score exceeds 0.35, the LLM critic automatically reverts to shadow mode for that cycle — even if live mode is configured. A struggling producer should not compound errors with LLM adjustments.

#### 3.1.2 Regime Matrix

Conditions every forecast on the current market regime. Different regimes get different confidence scaling.

**Global regime confidence caps:**

| Regime | Cap |
|--------|-----|
| BULL | 1.00 |
| BEAR | 0.70 |
| TRANSITION | 0.60 |
| CRISIS | 0.40 |

Producers can declare a `RegimeMatrix` with per-regime `RegimeConfig`:
- `confidence_multiplier`: scale candidate confidence
- `abstain`: always abstain in this regime
- `active_rules`: which rule groups run
- `min_confidence`: minimum to emit

#### 3.1.3 Differentiated Inputs

Each domain producer receives signals specific to its domain. This is handled at `collect()` + `normalize()` — each producer ingests only what it knows how to interpret. The intelligence layer doesn't change what producers ingest; it changes how the system evaluates the resulting forecasts.

#### 3.1.4 Producer Self-Memory

Adjusts a producer's confidence based on its own historical Brier score. Good calibration → confidence boost. Poor calibration → confidence penalty.

**Brier → delta mapping:**

| Brier Score | Confidence Delta |
|-------------|------------------|
| ≤ 0.10 | +0.15 |
| ≤ 0.20 | +0.08 |
| ≤ 0.25 | 0.00 |
| ≤ 0.33 | -0.10 |
| > 0.33 | -0.20 |

**Blending formula:**
```
blended = (1 - streak_weight) × long_term_delta + streak_weight × recent_delta
```

Where `streak_weight = 0.35` (recent performance gets 35% influence).

**Guardrails:**
- `max_delta = ±0.30` — confidence never shifts more than 30%
- `min_resolved = 5` — no adjustment until ≥5 resolved forecasts
- Action is never changed (confidence only)

#### 3.1.5 Adversarial Prosecutor

An LLM constructs the strongest possible case AGAINST each forecast. If the bear case overwhelms the bull case, the forecast is suppressed.

**Output:**
- `bear_strength` (0.0-1.0): strength of counter-case
- `bull_strength` (0.0-1.0): strength of thesis
- `suppress`: True if `bear_strength > bull_strength + 0.15`
- `confidence_boost` (0.0-0.15): bonus if bear case is weak

**Why it matters:** Catches correlated inputs — when all signals agree because they're measuring the same thing from different angles, the prosecutor finds the shared assumption.

### 3.2 P4: System-Level Intelligence

P4 layers operate across the ensemble. They add intelligence at the system level.

#### 3.2.1 Hierarchical Weighting

Dynamically adjusts per-domain weights in synthesis based on historical performance.

**The multiplier chain:**

```
final_multiplier = weighted_blend(
    0.40 × producer_reliability,   # trailing Brier (regime-aware)
    0.25 × asset_fit,              # per-asset historical Brier
    0.25 × regime_fit,             # domain performance in current regime
    0.10 × (1.0 - correlation_penalty)  # penalty for correlated domains
)
```

**Brier → multiplier conversion:**

| Brier Score | Multiplier |
|-------------|-----------|
| ≤ 0.10 | 1.50 |
| ≤ 0.20 | 1.30 |
| ≤ 0.25 | 1.00 |
| ≤ 0.30 | 0.85 |
| > 0.30 | 0.70 |

**Guardrails:**
- `MIN_MULTIPLIER = 0.1` — domain loses at most 90% of prior weight
- `MAX_MULTIPLIER = 2.0` — domain at most doubles prior weight
- `MIN_BRIER_SAMPLES = 5` — no adjustment until ≥5 resolved forecasts

#### 3.2.2 Multi-Horizon Forecasts

Each domain produces forecasts at domain-appropriate horizons with horizon-specific confidence scaling.

| Domain | Horizons | Confidence Scale | Confidence Cap |
|--------|----------|-----------------|----------------|
| TECHNICAL | 4h, 24h | 1.00, 0.90 | 0.85, 0.80 |
| TRADFI | 4h, 24h, 3d | 1.00, 1.05, 0.95 | 0.85, 0.88, 0.82 |
| ONCHAIN | 4h, 24h, 3d | 0.90, 1.00, 1.10 | 0.80, 0.85, 0.88 |
| SENTIMENT | 4h, 24h | 0.85, 1.00 | 0.75, 0.82 |

TradFi gets a slight 24h boost because basis/funding signals are more meaningful over 24h. On-chain gets a 3d boost because accumulation/distribution patterns play out over days.

#### 3.2.3 Cross-Producer Awareness (Novelty Penalty)

Gives each producer a single aggregate signal about what the rest of the system is thinking.

**Aggregate conviction:** `ConvictionStateReader` reads recent `FORECAST_V1` events (last 2 hours). For each asset: weighted average of `(confidence × direction_sign)` across all producers. Result: signed float in `[-1, +1]`.

**Novelty penalty mechanics:**
- High agreement with strong conviction → suppress confidence (adding noise, not signal)
- Contrarian signal → slight confidence boost (disagreement = information)
- Weak conviction → no penalty (brain is uncertain, all signals valuable)

**Tuning constants:**

| Constant | Value |
|----------|-------|
| `NOVELTY_CONVICTION_THRESHOLD` | 0.5 |
| `NOVELTY_AGREEMENT_PENALTY` | 0.15 |
| `NOVELTY_CONTRARIAN_BOOST` | 0.05 |
| `NOVELTY_MIN_CONFIDENCE` | 0.1 |

#### 3.2.4 The Meta-Producer

The meta-producer learns from the ensemble's historical track record. It reads only from performance tables and outcome history — never from raw market data.

**Hard constraint:** Inputs restricted to `FORECAST_V1`, `FORECAST_OUTCOME_V1`, and `producer_performance`/`producer_correlation` tables.

**Activation gate:** `MIN_FORECASTS_FOR_ACTIVATION = 500` resolved outcomes must exist before the meta-producer emits any non-abstention forecast. Below this, it always abstains with `INSUFFICIENT_DATA`.

**Pattern matching:**
1. Gets current ensemble state: latest action per producer for target asset (last 2 hours)
2. Searches historical episodes for matching ensemble patterns
3. Computes win rate and majority direction from matching episodes
4. Emits forecast only if:
   - `n ≥ MIN_SAMPLE_FOR_PATTERN` (10 matching episodes)
   - `win_rate ≥ WIN_RATE_THRESHOLD` (0.60)

**Shadow mode** (default): Even after activation, the meta-producer logs its would-be forecast but emits an abstention. The pattern library must mature before affecting synthesis.

---

## 4. The Compound Learning Loop

### 4.1 Forecast Immutability

Every `FORECAST_V1` event is:
- Timestamped at emission
- Hash-linked to the previous event
- Attributed to a specific producer with version
- Contains `action`, `confidence`, `horizon`, `asset`, `regime_tag`
- Immutable once written

The event store schema does not support UPDATE on forecast events. The hash chain breaks if any event is modified. This is deliberate.

### 4.2 Outcome Resolution (Brier Score)

The `OutcomeResolver` runs every 30 minutes via cron:

```bash
*/30 * * * * /usr/local/bin/b1e55ed resolve-outcomes
```

For each unresolved `FORECAST_V1` whose horizon has elapsed (+ 5-minute buffer):

1. Fetch prices at forecast time and resolution time
   - Primary: local `price_history` table
   - Fallback: Binance public klines API

2. Compute metrics:
   ```
   return_actual_pct = (actual_price - forecast_price) / forecast_price × 100
   direction_correct = (action == "long" and return > 0) or (action == "short" and return < 0)
   brier_score = (confidence - direction_correct)²
   ```

3. Write `FORECAST_OUTCOME_V1` event (immutable, deduplicated)

4. Record resolution in `forecast_resolution_state` table (idempotent)

**Brier score interpretation:**
- 0.00: perfect calibration (stated exactly what happened)
- 0.25: random guess baseline
- 1.00: maximally wrong (confident in opposite direction)

### 4.3 Karma Attribution

When a position closes:

1. Retrieve all `SIGNAL_ACCEPTED_V1` events linked to the trade
2. Phase 0: equal weights across contributing producers
3. Outcome mapping:
   - P&L > 0 → outcome = +1.0
   - P&L < 0 → outcome = -1.0
   - P&L ≈ 0 → outcome = 0.0

4. Karma update (EMA, α = 0.05):
   ```
   karma_new = karma_old × 0.95 + outcome × 0.05
   ```

5. Emit `ATTRIBUTION_OUTCOME_V1` event

**Contributor karma score** is a 5-factor composite:

```
score = 100 × clamp(
    0.35 × hit_rate_norm
  + 0.20 × calibration_norm
  + 0.20 × volume_norm
  + 0.15 × consistency_norm
  + 0.10 × recency
, 0, 1)
```

| Component | Weight | Source |
|-----------|--------|--------|
| `hit_rate_norm` | 35% | Profitable signals / resolved signals |
| `calibration_norm` | 20% | 1 - (brier_score / 0.25) |
| `volume_norm` | 20% | log₁₊(accepted) / log₁₊(100) |
| `consistency_norm` | 15% | √(streak_days) / √30 |
| `recency` | 10% | Days since last accepted signal |

### 4.4 Calibration and Isotonic Regression

The `forecast_calibration` table tracks per-producer, per-asset, per-horizon, per-regime Brier scores. This enables:

- **Self-memory adjustments** (§3.1.4): confidence ± based on historical Brier
- **Hierarchy adjustments** (§3.2.1): domain weight × based on reliability
- **Calibration curves**: stated confidence vs. actual hit rate

Future work: isotonic regression to map raw confidence to calibrated probability.

### 4.5 Domain Weight Adjustment

The learning loop adjusts domain weights based on rolling performance:

**Window:** 30 days (`ADJUSTMENT_WINDOW_DAYS = 30`)

**Observation threshold:** No adjustment until ≥20 closed positions (`MIN_OBSERVATIONS = 20`)

**Safety constraints:**
- `MAX_WEIGHT_DELTA = 0.02` (±2% per cycle)
- `MIN_DOMAIN_WEIGHT = 0.05` (5% floor)
- `MAX_DOMAIN_WEIGHT = 0.40` (40% ceiling)

**Algorithm:**
1. For each closed position: outcome sign from `realized_pnl`
2. Pull domain scores at entry from `conviction_log`
3. For each domain: compute correlation between score and outcome
4. Translate correlation → delta (clamped to ±MAX_WEIGHT_DELTA)
5. Clamp to floor/ceiling, renormalize to sum 1.0
6. Persist to `data/learned_weights.yaml`

**Overfitting protection:** If 3 consecutive cycles degrade performance, weights revert to preset defaults.

### 4.6 The 500-Outcome Gate

The meta-producer's activation gate is not arbitrary. It reflects the minimum sample size for meaningful pattern statistics.

**Why 500:**
- At 10 trades/day, 500 outcomes = ~50 days
- Statistical power for detecting 60% win rate vs 50% baseline requires n ≈ 100+ per pattern
- With pattern diversity, 500 total outcomes provides ~50+ outcomes per major ensemble pattern
- Below this threshold, pattern matching is noise-fitting

The gate is a hard requirement. The meta-producer cannot be forced into live mode below 500 resolved outcomes.

---

## 5. Falsifiability Mechanisms

### 5.1 The Benchmark Stack (4 benchmarks, must beat all)

Four benchmarks run in parallel, producing signals through the same pipeline as real producers:

| Benchmark | Logic | Purpose |
|-----------|-------|---------|
| **Momentum** | Long if price > 20-period EMA, short if below | Naive trend-following baseline |
| **Flat** | Always neutral (confidence = 0.0) | Catches overtrading |
| **Equal-Weight** | Average direction of all active signals | Tests whether weighting adds value |
| **Discretionary** | Operator manual override | Human benchmark |

**The rule:** Brain must beat ALL FOUR to claim edge. Beating three but losing to one is not edge — it's a regime fit that will eventually revert.

Benchmarks flow through the same `SIGNAL_ACCEPTED_V1` → karma path as real signals. They get karma scores. Karma for benchmarks quantifies "brain adds X% vs naive momentum."

### 5.2 Confidence Stratification Test (primary proof metric)

The 30-day proof metric is not raw P&L (too noisy at n < 50 trades). The primary metric is confidence stratification:

**Question:** Do signals with confidence > 0.65 outperform signals with confidence < 0.45 after fees?

**Implementation:** `StratificationTracker` tags each signal:
- High: confidence ≥ 0.65
- Mid: 0.45 ≤ confidence < 0.65
- Low: confidence < 0.45

On outcome resolution: update bucket running stats. Report via `b1e55ed report --stratification`.

**Why this is the primary proof:**
- It tests calibration, not luck
- It's meaningful at small sample sizes (comparing buckets, not absolute return)
- If high-confidence signals don't outperform low-confidence, the weighting system is broken

### 5.3 Brier Score as Quality Gate

Brier score is the calibration metric that drives all adaptive behavior:

**At producer level:**
- Self-memory adjusts confidence ± based on trailing Brier
- LLM critic reverts to shadow if Brier > 0.35
- Hierarchy engine weights domains by Brier reliability

**At system level:**
- Aggregate Brier exposed via oracle provenance endpoint
- External verifiers can compare claimed calibration to actual

**Interpretation:**
- Brier < 0.20: good calibration (keep doing what you're doing)
- Brier 0.20-0.25: marginal (slight edge over random)
- Brier > 0.25: worse than random (something is broken)

### 5.4 Kill Switch Conditions

Kill switches are the system's admission that it can fail. They are not configurable — they are enforced.

| Condition | Trigger | Why It Matters |
|-----------|---------|----------------|
| 3 consecutive losses | Position close with P&L < 0, 3x | Regime may have shifted |
| Single loss > 2% | Realized loss > 2% portfolio | Position sizing failed |
| Open risk > 5% | Aggregate exposure > 5% | Risk concentration |
| Data feed degraded | 0 events in last 2 cycles | Garbage in, garbage out |
| Fill divergence > 0.5% | Actual vs intended price | Execution quality problem |

On trigger:
- DEFENSIVE level: no new positions, notify operator
- CAUTION level: flatten affected signals to neutral, audit

---

## 6. The Contributor Network

### 6.1 Producer Registration and Identity

Contributors register via:
- CLI: `b1e55ed register`
- API: `POST /api/v1/contributors/register`
- Oracle relay: `POST /api/v1/oracle/contributors/register` (no auth)

Each contributor receives:
- `contributor_id`: internal primary key
- `node_id`: stable external identity (Ethereum address with `0xb1e55ed` prefix via The Forge)
- EAS attestation (optional): off-chain Ethereum Attestation Service record

Signals are attributed to contributors via `node_id` in the submission payload.

### 6.2 Karma as On-Chain-Equivalent Attribution

Karma is not a trust score. It does not predict future performance. It is a compressed historical summary of past outcomes — nothing more.

**Anti-gaming measures:**

| Measure | What It Prevents |
|---------|------------------|
| Volume counts accepted only | Spam submissions don't inflate score |
| Streak counts accepted days | Drip-farming (1 signal/day, all rejected) |
| Hit rate requires resolution | Can't inflate by avoiding outcomes |
| Brier score penalty | Confident-but-wrong signals hurt |
| Acceptance rate gate | < 10% acceptance → score = 0 |

**Sybil note:** Karma is not Sybil-resistant until Forge cost is implemented. A bad actor can register multiple contributors, run them in parallel, and cherry-pick the winner. Treat contributors with < 30 resolved signals with skepticism.

### 6.3 The Oracle

The oracle exposes contributor provenance for external verification:

**Endpoint:** `GET /api/v1/oracle/producers/{id}/provenance`

**Response:**
```json
{
  "contributor_id": "0xb1e55ed...",
  "chain_verified": true,
  "total_forecasts": 847,
  "resolved_forecasts": 812,
  "brier_score": 0.19,
  "karma_score": 74.2,
  "first_signal": "2026-01-15T...",
  "last_signal": "2026-03-04T..."
}
```

**`chain_verified`:** Calls `verify_hash_chain(fast=True, last_n=100)` — not just "hash exists" but "hash chain validates."

No authentication required. The oracle is a public good.

---

## 7. Shadow-First Philosophy

### 7.1 Why Every Intelligence Layer Defaults to shadow=True

Shadow mode is the most important design pattern in the intelligence layer. Every LLM-based and adaptive layer defaults to `shadow=True`.

**What shadow mode means operationally:**
- The layer runs its full computation
- The result is logged
- The candidate forecast passes through unchanged
- No forecast is suppressed, boosted, or modified by a shadow layer

**Why this is the right default:**
- New layers have no track record
- Shadow data lets you compare "what would have happened" vs actual outcomes
- You can validate each layer independently before going live
- If an LLM hallucinates or a pattern goes wrong, shadow mode means zero production impact

### 7.2 The Observation Period

The system does not trust itself until it has earned trust.

| Layer | Observation Data Needed | What Activates |
|-------|-------------------------|----------------|
| Self-memory | 5 resolved forecasts per producer | Confidence ± Brier delta |
| Hierarchy | 5 resolved forecasts per domain | Domain weight multipliers |
| Meta-producer | 500 total resolved outcomes | Pattern logging begins |
| Meta-producer live | 500 + 10 matching episodes + 60% win rate | Live ensemble forecasts |

**Cold start behavior:**
- Days 1-30: observe only, no weight adjustments
- Days 30-90: warm period, MAX_WEIGHT_DELTA halved to ±1%
- Days 90+: full adjustments (±2%)

### 7.3 Promotion Criteria

To enable live mode for a shadow layer:

**LLM Critic:**
- Run shadow for ≥2 weeks
- `get_shadow_comparison()` shows improved calibration
- Suppression rate is reasonable (not suppressing everything)

**Prosecutor:**
- Shadow logs show meaningful bear/bull strength separation
- Catches genuine correlated-input problems

**Novelty:**
- ≥3 producers running
- Brain conviction is meaningful

**Meta-Producer:**
- ≥500 resolved outcomes
- Pattern library shows win_rate ≥ 0.60 on ≥10 episodes
- Shadow logs reviewed for ≥1 month

---

## 8. Current Status and Roadmap

### 8.1 Beta.8 State

**What works:**
- 13 producers across 6 domains
- 7-layer interpreter stack (all shadow by default)
- Event-sourced database with hash chain
- Outcome resolution via Brier score (30-min cron)
- Karma attribution on position close (EMA α=0.05)
- 4 benchmarks running in parallel
- Kill switches enforced (all 5 conditions)
- Cockpit dashboard with 30s HTMX refresh
- Auto-paper-trade on confidence ≥ 0.65
- Stratification tracking and CLI reporting
- Oracle endpoint for external verification

**What's in shadow mode:**
- LLM critic (observing, not adjusting)
- Prosecutor (observing, not suppressing)
- Novelty penalty (observing, not penalizing)
- Meta-producer (pattern logging, always abstains)

### 8.2 Data Accumulation Timeline

```
Week 1:     Self-memory activates for producers with ≥5 resolved forecasts
Week 2-4:   ~500 outcomes accumulate; MetaProducer begins shadow logging
Month 2:    Shadow logs have enough data to evaluate LLM critic
Month 3:    Regime-conditional stats become reliable
Month 6:    Full ensemble pattern library; all layers can be evaluated
```

**Phase 0 complete when:**
- ≥20 paper trades completed
- Stratification shows high > low after fees
- All 4 benchmarks running for 14+ days
- Cockpit reviewed daily for 1 week without issues

### 8.3 Open Problems

**Sybil resistance:** Karma is gameable until registration has non-trivial cost. Planned: Forge-based proof of work or on-chain stake.

**Regime detection:** Current regime tagging is rule-based (BULL/BEAR/TRANSITION/CRISIS). Planned: probabilistic regime model with uncertainty.

**Calibration curves:** Current Brier score is aggregate. Planned: per-confidence-bucket calibration with isotonic regression for probability mapping.

**Multi-asset correlation:** Current hierarchy penalizes correlated domains but not correlated assets. Planned: cross-asset correlation in synthesis.

**External data quality:** Binance public API fallback is best-effort. Planned: redundant price feeds with median selection.

---

## References / Appendix

### A. Key Source Files

| File | What It Contains |
|------|-----------------|
| `engine/core/interpreter.py` | `Interpreter`, `LLMCriticInterpreter`, `SelfMemoryInterpreter`, `ProsecutorInterpreter`, `NoveltyInterpreter` |
| `engine/core/regime.py` | `RegimeMatrix`, `RegimeConfig`, `REGIME_CAPS` |
| `engine/core/self_memory.py` | `SelfMemory`, `SelfMemoryConfig` |
| `engine/core/prosecutor.py` | `Prosecutor`, `ProsecutorConfig`, `ProsecutionResult` |
| `engine/core/novelty.py` | `compute_novelty_penalty`, `NoveltyResult` |
| `engine/brain/hierarchy.py` | `HierarchyEngine`, `HierarchyFactors`, `HierarchyResult` |
| `engine/brain/outcome_resolver.py` | `OutcomeResolver`, `run_resolver` |
| `engine/brain/performance_aggregator.py` | `PerformanceAggregator` |
| `engine/producers/meta.py` | `MetaProducer` |
| `engine/execution/karma.py` | `KarmaEngine`, `attribute_outcome` |

### B. Database Tables

| Table | Purpose |
|-------|---------|
| `events` | Hash-chained event store |
| `forecast_resolution_state` | Idempotent outcome resolution tracking |
| `forecast_calibration` | Per-producer Brier scores |
| `producer_performance` | Rolling producer stats |
| `producer_correlation` | Pairwise producer agreement rates |
| `producer_karma` | EMA karma scores |
| `signal_stratification` | Confidence band outcome tracking |
| `system_state` | Kill switch and cockpit state |
| `contributors` | Registered contributor identities |
| `karma_intents` | Trade → karma attribution links |

### C. Configuration Reference

| Parameter | Default | What It Controls |
|-----------|---------|------------------|
| `brain.auto_paper_trade` | `true` | Auto-execute on high confidence |
| `weights.*` | sum to 1.0 | Domain synthesis weights |
| `B1E55ED_LLM_CRITIC_SHADOW` | `true` | LLM critic shadow mode |
| `B1E55ED_PROSECUTOR_SHADOW` | `true` | Prosecutor shadow mode |
| `MIN_FORECASTS_FOR_ACTIVATION` | 500 | Meta-producer activation gate |
| `MIN_SAMPLE_FOR_PATTERN` | 10 | Meta-producer pattern threshold |
| `WIN_RATE_THRESHOLD` | 0.60 | Meta-producer win rate gate |

### D. Glossary

| Term | Definition |
|------|------------|
| **Brier score** | `(confidence - outcome)²` — calibration metric where 0 is perfect |
| **Karma** | 5-factor composite reputation score for contributors |
| **PCS** | Position Conviction Score — brain output, 0-100 scale |
| **Shadow mode** | Layer observes and logs but does not mutate forecasts |
| **Stratification** | Bucketing signals by confidence for calibration testing |
| **The Forge** | Ethereum vanity address generator for `0xb1e55ed` prefix |

---

*"The system that learns from its own outcomes will outperform systems that don't."*

*The code remembers. The hex is blessed: 0xb1e55ed.*
