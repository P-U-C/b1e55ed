# b1e55ed: A Falsifiable Trading Intelligence Engine for Systematic Crypto

**Version**: 4.0.0 | **Date**: March 2026

---

## Abstract

Most crypto "alpha" is unverifiable. Signal services give you a call with no prior calibration, no track record, no accountability. Discretionary traders cannot separate skill from luck. Even systematic traders rarely close the attribution loop — they know the P&L but not which signals drove which trades, which producers were right, or whether their confidence calibration reflects reality.

b1e55ed is a **falsifiable trading intelligence engine** designed to close that loop. Every forecast is an immutable, timestamped probability statement attributed to a specific producer. Every outcome is resolved against actual prices. Every score feeds back into weights and confidence calibration. The system cannot retroactively explain away losses because the evidence chain is hash-linked and externally verifiable.

The benchmark is not beating a market index — it's beating flat/no-trade. The system must prove it earns its execution cost. Four benchmarks run in parallel (naive momentum, equal-weight ensemble, flat/no-trade, discretionary override), and the brain must outperform all four to claim edge. The primary proof metric is confidence stratification: do signals with confidence > 0.65 outperform signals with confidence < 0.45 after fees?

The current implementation (beta.8) runs 13 domain producers through a 7-layer interpreter stack, resolves outcomes every 30 minutes via Brier score, and updates producer karma via a directional EMA (α=0.05). All adaptive layers default to shadow mode — they observe and log without mutating forecasts. The meta-producer activates only after 500 resolved outcomes accumulate (an operational minimum calibrated for the effect sizes we aim to detect). This is deliberate: the system must prove its calibration before it earns trust.

---

The decisive falsification test: do high-confidence forecasts produce better economic outcomes than low-confidence forecasts, net of fees, under identical execution assumptions? This question — not aggregate P&L, not directional accuracy — is the proof standard the system is designed to answer.
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

### 1.4 Competitive Positioning

The closest analogues are:
- **Numerai**: crowdsourced model tournament where producers cannot verify their own contribution to portfolio returns. Aggregation is opaque by design.
- **Polymarket**: prediction markets providing calibrated probabilities, but no synthesis into portfolio construction or attribution.
- **Traditional signal aggregation**: vendors providing signals without systematic calibration, attribution, or closed-loop feedback.

b1e55ed's structural differentiator: closed-loop attribution that producers and buyers can independently audit. Producers receive a portable, verifiable track record (karma + Brier history via oracle). Buyers receive machine-verified producer history before capital allocation. The oracle decouples the accountability mechanism from the execution layer — verification does not require trusting the operator.

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

The event store enforces append-only writes at the application layer. Each event carries a `prev_hash` field referencing the SHA-256 hash of the prior event, forming a linked chain. Retroactive modification of any event requires recomputing the hash chain from the tampered point forward — detectable on any replay or audit. The `verify_hash_chain()` function validates the full chain on demand.

**Current architecture**: append-only, hash-linked, application-layer enforcement.

**Audit roadmap**: cryptographic anchoring to an external chain (EAS or equivalent) for operator-independent verification. Until that ships, the hash chain provides auditability within the trust boundary of the operator.

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

#### Bootstrapping and Cold-Start

The system is not inert before external contributors join. Thirteen internal producers — spanning on-chain capital flows, technical analysis, TradFi basis and funding, sentiment, and social signals — run from first deployment. These producers generate the initial outcome volume that calibration, isotonic regression, and the meta-producer require.

External contributors join a system with an existing track record. The first 500 resolved outcomes — the meta-producer activation gate — are reachable without a single external producer. This eliminates the cold-start failure mode: the system begins learning from day one, independent of contributor network size.

### 2.3 The Interpreter Stack (P3/P4 — 7 Layers)

Every producer's raw output passes through a layered interpreter chain before becoming a `FORECAST_V1` event. The stack is applied automatically by `BaseProducer.emit_forecast()`:

```
┌─────────────────────────────────────────────────────────┐
│                   NoveltyInterpreter                    │  ← P4.3: redundancy discount
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

> **Definition — Confidence**: A producer's confidence value is its stated probability that the following canonical event resolves as true: the forecast's target asset closes above (LONG) or below (SHORT) its entry reference price after horizon H, net of execution fees. This is the event the Brier score evaluates. Every confidence value in the system refers to this definition. Producers with different implicit event definitions are not comparable; the system enforces the canonical definition at resolution time via `OutcomeResolver`.

### 2.4 Evaluation Layers

The system distinguishes three evaluation layers that are related but not identical:

**Layer 1 — Forecast Quality**: Did the forecast resolve correctly under the canonical event definition? Measured by Brier score per producer per cycle. A producer can be well-calibrated (good Brier) while being economically useless after fees and slippage.

**Layer 2 — Attribution Quality**: Which producers contributed to synthesis, and at what weight? Tracked by karma EMA. A producer can have high karma (consistent directional contribution) without strong Brier calibration, and vice versa.

**Layer 3 — Portfolio Performance**: Did the resulting positions outperform all four benchmarks after fees, slippage, and risk constraints? This is the only layer that directly measures economic edge.

The decisive falsification test operates at Layer 3: do forecasts assigned higher confidence produce better realized economic outcomes than lower-confidence forecasts, net of fees, under identical execution assumptions? Higher directional accuracy is necessary but not sufficient. Higher Brier score is necessary but not sufficient. The test is economic.

### 2.5 Brain Synthesis and Conviction

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

### 2.6 Position Sizing

Position sizing is confidence-sensitive — high-confidence forecasts deploy more capital than low-confidence ones. The exact sizing policy is configurable and not central to the attribution thesis described here.

### 2.7 Execution and Kill Switches

Execution follows conviction through a preflight check, then submits to paper or live broker. Five kill switch conditions are enforced:

| Condition | Trigger | Action | Level |
|-----------|---------|--------|-------|
| Consecutive losses | 3 in a row | Pause signal generation, notify | DEFENSIVE |
| Single loss | > 2% portfolio | Auto-close position | DEFENSIVE |
| Total open risk | > 5% portfolio | Block new positions in preflight | CAUTION |
| Data feed degraded | Any producer fails > 2 cycles | Flatten domain signals to neutral | CAUTION |
| Fill divergence | Actual fill > 0.5% from intended | Pause, investigate | CAUTION |

Kill switches are not suggestions. They are hard gates that override conviction.

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

#### 3.2.3 The Redundancy Discount (Correlation Discounting)

**The Correlated-Producer Problem**

In a multi-producer ensemble, correlated signals pose a fundamental threat: N technical-analysis producers all emit similar signals during trending markets, dominating synthesis through volume rather than information content. A brain that naively weights by producer count will overweight redundant signals.

**NoveltyInterpreter as the Solution**

The P4.3 `NoveltyInterpreter` directly addresses this problem. It reads aggregate brain conviction (the running weighted sum of all `FORECAST_V1` events in the prior 2-hour window) and penalizes any producer whose forecast agrees with the existing consensus.

The novelty penalty estimates redundancy from rolling agreement frequency between a producer's forecast direction and the current ensemble direction across matched assets and horizons. The exact correlation measure is specified but subject to calibration; the formula in the source code is the authoritative reference.

**Redundancy discount formula:**

$$\text{confidence}_{\text{adjusted}} = \text{confidence} \times (1 - \text{novelty\_penalty})$$

Where the novelty penalty is proportional to existing conviction magnitude when the new forecast agrees with aggregate direction.

**Mechanically:** A producer saying "long" when five others have already said "long" with high conviction receives a confidence penalty proportional to the existing conviction magnitude. A contrarian signal (disagreeing with aggregate) receives a slight boost.

**Tuning constants:**

| Constant | Value | Purpose |
|----------|-------|---------|
| `NOVELTY_CONVICTION_THRESHOLD` | 0.5 | Minimum aggregate conviction to trigger penalty |
| `NOVELTY_AGREEMENT_PENALTY` | 0.15 | Maximum penalty for redundant agreement |
| `NOVELTY_CONTRARIAN_BOOST` | 0.05 | Bonus for disagreeing with consensus |
| `NOVELTY_MIN_CONFIDENCE` | 0.1 | Floor after penalty applied |

**Why this works:** A producer that provides genuinely new information will either (a) disagree with consensus (contrarian boost), or (b) agree but when conviction is low (no penalty). A producer that merely echoes existing consensus when the brain is already confident is penalized — its signal is redundant, not additive.

#### 3.2.4 The Meta-Producer

The meta-producer learns from the ensemble's historical track record. It reads only from performance tables and outcome history — never from raw market data.

**Hard constraint:** Inputs restricted to `FORECAST_V1`, `FORECAST_OUTCOME_V1`, and `producer_performance`/`producer_correlation` tables.

**Activation gate:** `MIN_FORECASTS_FOR_ACTIVATION = 500` resolved outcomes must exist before the meta-producer emits any non-abstention forecast. Below this, it always abstains with `INSUFFICIENT_DATA`. (See §4.7 for the statistical justification of this threshold.)

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

4. **Directional karma update:**
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

#### Karma and Brier: Complementary, Not Redundant

Karma and Brier score serve distinct purposes. Brier score measures **calibration quality** — whether a producer's stated probabilities match realized outcome frequencies. Karma is an **operational weighting signal** — a directional EMA tracker that determines how much a producer's current forecasts influence synthesis.

The karma update rule `karma_new = karma_old × 0.95 + outcome × 0.05` is intentionally simple: it captures contribution to directional outcomes, not calibration quality. This is a design choice: calibration analysis is expensive (requires resolved outcomes at scale), while directional karma can update every cycle.

The two signals are complementary diagnostics:
- High Brier + low karma: well-calibrated producer not contributing to profitable synthesis
- Low Brier + high karma: producer gaming easy directional calls without calibration quality
- High Brier + high karma: trusted producer — target state

Both metrics must be healthy. Neither alone is sufficient for elevated synthesis weight.

#### Future Hardening: Sharpness Weighting

*Status: specified, not yet deployed in beta.8*

To prevent Goodhart collapse toward timid forecasts, a sharpness multiplier is under evaluation:

```
sharpness = |confidence - 0.5| × 2
karma_new = karma_old × 0.95 + outcome × sharpness × 0.05
```

This rewards bold correct forecasts disproportionately. A producer who issues confident forecasts and is right will accumulate karma faster than a producer who hedges at 0.55. A producer who issues confident forecasts and is wrong will lose karma faster.

Requires a calibration quality gate to prevent overconfidence gaming. The sharpness mechanism addresses the resolution component of Brier decomposition — ensuring that forecasters cannot game the system by clustering predictions near the base rate.

#### Difficulty-Adjusted Sharpness

*Status: research design*

The basic sharpness formula rewards resolution but does not account for prediction difficulty. A producer who confidently predicts BTC will rise during a strong uptrend is making an easy call — the base rate already favors that direction. The difficulty-adjusted sharpness formula conditions the resolution multiplier on implied probability from market state:

```
base_rate = regime_directional_bias(asset, regime)  # e.g., 0.65 for BULL
difficulty = 1 - |base_rate - 0.5| × 2              # harder when base_rate ≈ 0.5
sharpness = |confidence - 0.5| × 2
adjusted_sharpness = sharpness × difficulty

karma_new = karma_old × 0.95 + outcome × adjusted_sharpness × 0.05
```

**Interpretation:**
- `difficulty = 1.0` when `base_rate = 0.5` (maximum uncertainty, hardest to predict)
- `difficulty = 0.0` when `base_rate = 0.0` or `1.0` (deterministic, trivial to predict)
- A bold correct forecast in a 50/50 regime earns full sharpness credit
- A bold correct forecast in a trending regime earns discounted sharpness credit

This addresses the **bold-on-easy gaming vector**: a producer cannot farm karma by confidently calling direction during obvious trends. The regime detector provides the base rate estimate; the difficulty adjustment ensures that karma accumulation reflects genuine forecasting skill, not regime tailwinds.

**Calibration requirement:** The `base_rate` estimate must itself be calibrated. If the regime detector systematically misjudges directional bias, the difficulty adjustment will misattribute skill. Initial implementation uses a 20-period rolling directional accuracy as the base rate proxy.

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

### 4.6 The Goodhart Risk in Pure Calibration

**The Problem**

A naive karma system that rewards only Brier score calibration creates a perverse incentive. The Brier score for a binary forecast decomposes as:

$$\text{Brier} = \text{Calibration} + \text{Resolution} - \text{Uncertainty}$$

Where:
- **Calibration**: Do stated probabilities match actual frequencies? (0.7-confidence forecasts should be correct 70% of the time)
- **Resolution**: How much do forecasts differ from the base rate? (Informativeness)
- **Uncertainty**: Irreducible noise in the outcome

A rational producer in a system that only rewards calibration will cluster forecasts near the base rate (typically ~0.50 for directional predictions). This minimizes Brier downside: a 0.52-confidence forecast that's wrong incurs Brier = (0.52 - 0)² = 0.27, barely worse than random. A 0.85-confidence forecast that's wrong incurs Brier = (0.85 - 0)² = 0.72, much worse.

The result: a system full of timid, technically-well-calibrated, informationally-useless forecasts. This is the Goodhart's Law failure mode for prediction markets (Goodhart, 1984).

**The Mitigation**

The sharpness weighting mechanism (§4.3, Future Hardening) is designed to counter this. By rewarding resolution disproportionately, the system incentivizes bold, correct forecasts over timid ones. This is under evaluation but not yet deployed.

### 4.7 The 500-Outcome Gate: Statistical Justification

The meta-producer's activation gate of 500 resolved outcomes derives from power analysis for detecting meaningful forecast skill.

The 500-outcome gate is an operational minimum chosen to reduce overfitting risk before the meta-producer influences synthesis. At this sample size across multiple producers, assets, and regimes, statistical regularities become distinguishable from noise for the effect sizes the system is designed to detect. The exact threshold is a conservative hyperparameter — too low risks activating on noise, too high delays genuine learning.

**The Detection Problem**

We want to detect whether a producer's Brier score is significantly better than random guessing. Define:
- $H_0$: Producer Brier = 0.25 (random binary baseline)
- $H_1$: Producer Brier = 0.20 (20% improvement)
- $\alpha = 0.05$ (Type I error rate)
- $\beta = 0.20$ (Type II error rate, i.e., 80% power)

**Brier Score Variance**

For calibrated binary forecasts, the variance of the Brier score is approximately:

$$\text{Var}(\text{Brier}) \approx p(1-p)(1-2p)^2 + p^2(1-p)^2$$

For $p \approx 0.5$, this simplifies to $\sigma^2 \approx 0.0625$.

**Sample Size Calculation**

Using the standard power analysis formula for comparing means:

$$n \approx \frac{(z_\alpha + z_\beta)^2 \times 2\sigma^2}{\Delta^2}$$

Where:
- $z_\alpha = 1.96$ (two-tailed)
- $z_\beta = 0.84$
- $\Delta = 0.05$ (effect size: 0.25 - 0.20)
- $\sigma^2 = 0.0625$

$$n \approx \frac{(1.96 + 0.84)^2 \times 2 \times 0.0625}{0.05^2} = \frac{7.84 \times 0.125}{0.0025} \approx 392$$

**Conservative Adjustment**

The theoretical minimum is ~400 outcomes. However:
- Crypto forecast variance is often higher than theoretical due to regime shifts
- Pattern diversity requires multiple outcomes per ensemble configuration
- Statistical estimates should include safety margin

The 500 figure sits at the upper end of the power-analysis range and provides:
- ~50 days of data at 10 forecasts/day
- Sufficient outcomes per major ensemble pattern (~50+)
- Buffer against variance underestimation

### 4.8 Regime-Conditional Karma

**The Non-Stationarity Problem**

Karma uses an EMA with $\alpha = 0.05$, meaning ~95% of the score reflects the last ~100 outcomes. This creates a regime-mismatch failure mode:

A trending-market specialist accumulates maximum karma during a bull market, then carries maximum synthesis weight into a regime transition — exactly when their signals become least reliable. The karma system is stationary; markets are not.

**Solution 1: Regime-Conditional Karma Tables**

*(Research design, not yet deployed)*

Maintain separate karma tables per detected regime:

| Table | Applies When |
|-------|--------------|
| `karma_bull` | `RegimeDetector.regime == BULL` |
| `karma_bear` | `RegimeDetector.regime == BEAR` |
| `karma_transition` | `RegimeDetector.regime == TRANSITION` |
| `karma_crisis` | `RegimeDetector.regime == CRISIS` |

At regime transition, the incoming regime's karma table receives higher weight in synthesis:

$$\text{karma}_{\text{effective}} = 0.7 \times \text{karma}_{\text{current\_regime}} + 0.3 \times \text{karma}_{\text{global}}$$

This prevents producers from carrying cross-regime reputation they haven't earned.

**Solution 2: Accelerated Decay During Transitions**

*(Research design, not yet deployed)*

When `RegimeDetector` signals `TRANSITION`:
- Temporarily increase EMA $\alpha$ from 0.05 to 0.15 (3× faster forgetting)
- Maintain accelerated decay until regime stabilizes (2 consecutive non-TRANSITION readings)

This forces faster reputation re-establishment when the market environment changes.

**Implementation Status:** Both mechanisms are specified but currently in shadow mode. The system logs what karma would be under regime-conditional rules without affecting live synthesis.

#### Meta-Labeling and Regime-Conditional Performance

Karma scores are not regime-portable. A producer that correctly forecasts BTC direction during a low-entropy trending regime accumulates karma that may not reflect skill in a high-entropy choppy regime. The design mirrors López de Prado's meta-labeling framework (2018): outcomes should be labeled not just by direction but by the difficulty of the prediction environment.

b1e55ed's approach: regime-conditional karma tables. The system maintains separate karma histories per detected regime (BULL/BEAR/TRANSITION/CRISIS). At regime transition, synthesis weights draw preferentially from the incoming regime's karma table, preventing cross-regime karma bleed. Additionally, during detected regime transitions, the EMA decay accelerates (α → 0.15) to speed forgetting of the prior regime's signal quality.

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

All benchmark comparisons run under identical assumptions: same market data source, same fee model, same slippage model, same execution timestamps, same rebalance cadence, and same exposure constraints. A benchmark that runs under different assumptions is not a valid comparison.

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

## 6. The Oracle as a Verifiable Signal Marketplace

### 6.1 Beyond Infrastructure: The Platform Play

The oracle is not merely a read-only projection layer. It is b1e55ed's most commercially differentiated component — the foundation of a **verifiable signal marketplace**.

**The Core Value Proposition**

The oracle answers a question that no existing crypto signal platform can answer credibly:

> "Does this signal provider have a machine-verified track record, or are they just claiming one?"

Traditional signal services operate on trust. The oracle operates on verification.

### 6.2 Producer Registration and Identity

Contributors register via:
- CLI: `b1e55ed register`
- API: `POST /api/v1/contributors/register`
- Oracle relay: `POST /api/v1/oracle/contributors/register` (no auth)

Each contributor receives:
- `contributor_id`: internal primary key
- `node_id`: stable external identity (Ethereum address with `0xb1e55ed` prefix via The Forge)
- EAS attestation (optional): off-chain Ethereum Attestation Service record *(roadmap)*

Signals are attributed to contributors via `node_id` in the submission payload.

Producer identities are cryptographically persistent: each producer is bound to a keypair, and forecast history is inseparable from that key. A producer's track record cannot be reset or transferred.

Cryptographic persistence supports continuity and auditability. It does not by itself prevent a single actor from registering multiple keys. Sybil resistance in b1e55ed relies on layered friction:
1. **Karma cold-start**: new producers carry zero karma weight. There is no shortcut to influence.
2. **EAS attestation**: registration via the oracle requires an Ethereum Attestation Service attestation, creating a cost and identity signal *(roadmap)*.
3. **Correlation detection**: P4.3 (`NoveltyInterpreter`) penalizes producers whose forecasts align with existing brain conviction — a Sybil cluster submitting identical signals amplifies the penalty, not the weight.

These are friction mechanisms, not cryptographic proofs of uniqueness. The threat model acknowledges that sophisticated actors can operate multiple producers; the system's defense is that doing so is costly and detectable via correlation analysis.

### 6.3 The Product: Verifiable Track Records

**Endpoint:** `GET /api/v1/oracle/producers/{id}/provenance`

**Response:**
```json
{
  "contributor_id": "0xb1e55ed...",
  "chain_verified": true,
  "total_forecasts": 847,
  "resolved_forecasts": 812,
  "brier_score": 0.19,
  "brier_by_regime": {
    "BULL": 0.17,
    "BEAR": 0.23,
    "TRANSITION": 0.21,
    "CRISIS": 0.28
  },
  "directional_accuracy": 0.58,
  "karma_score": 74.2,
  "karma_by_regime": {
    "BULL": 82.1,
    "BEAR": 61.3,
    "TRANSITION": 68.7,
    "CRISIS": 54.2
  },
  "sharpness_ratio": 0.72,
  "avg_confidence": 0.68,
  "first_signal": "2026-01-15T...",
  "last_signal": "2026-03-04T...",
  "hash_chain_root": "0x7f3a..."
}
```

**Key Fields:**
- `chain_verified`: Calls `verify_hash_chain(fast=True, last_n=100)` — not just "hash exists" but "hash chain validates from origin"
- `brier_by_regime`: Performance breakdown by market regime — reveals regime specialists vs all-weather producers
- `sharpness_ratio`: Average confidence distance from 0.5 — distinguishes bold forecasters from hedgers
- `hash_chain_root`: Merkle root of all forecasts, enabling external verification

### 6.4 The Trust Model

The oracle serves producer track records from the same append-only, hash-linked event store that drives the engine. The system is designed for cryptographic auditability — hash-linked today, external chain anchoring on roadmap.

An operator running b1e55ed cannot retroactively edit a forecast because:
1. The event store is append-only (no UPDATE on forecast events)
2. Each event is hash-linked to its predecessor
3. The oracle can recompute the hash chain from origin
4. Any tampering breaks the chain and flips `chain_verified` to `false`

### 6.5 The Customer

**Primary:** Any trader, fund, or algorithmic system that wants access to machine-verified producer track records without operating the full b1e55ed stack.

**Use cases:**
- Fund evaluating signal providers before allocation
- Trader vetting a CT alpha caller's actual history
- System integrating third-party signals with trust requirements
- Researcher studying forecast calibration across the crypto industry

**What they're buying:** Not the signals themselves (those require contributor agreement). They're buying the *verification* — the proof that a claimed track record is real.

### 6.6 The Value Flow

```
Producer → Forecasts → b1e55ed → Outcomes → Karma
                                    ↓
                             Oracle (public)
                                    ↓
                           Consumer queries
                                    ↓
                        Verification → Trust → Allocation
```

**For producers:** Karma becomes portable reputation. A producer with high karma verified by the oracle can charge for signal access, knowing their track record is independently verifiable. The oracle enforces attribution — downstream consumers can verify that the producer actually made the calls they claim.

**For consumers:** Access to a verifiable signal quality database. No more trusting screenshots of Telegram calls.

**For the platform:** Network effects compound. More producers → better verification → more consumers → more producers. The oracle is the coordination layer.

### 6.7 The Platform Play

b1e55ed as infrastructure + oracle = a verifiable signal marketplace.

**Phase 1 (current):** Oracle as public good. No authentication required. Establishes credibility and network effects.

**Phase 2:** Premium oracle tier with:
- Real-time provenance updates (vs 30-min batch)
- Webhook notifications on producer karma changes
- Bulk query API for systematic consumers
- Historical regime-conditional performance data

**Phase 3:** Signal marketplace:
- Producers list signals for subscription (price in USDC/ETH)
- Oracle enforces attribution and verifies track record
- Settlement on-chain with oracle-verified karma as collateral
- Revenue share: platform takes X% of signal subscription revenue

**The asymmetric upside:** The oracle turns b1e55ed from a trading system into a platform. Producers compete on verified track record, not claims. Consumers pay for access to verifiable alpha. The oracle is the trust layer that makes the marketplace possible.

### 6.8 Anti-Gaming Measures

| Measure | What It Prevents |
|---------|------------------|
| Volume counts accepted only | Spam submissions don't inflate score |
| Streak counts accepted days | Drip-farming (1 signal/day, all rejected) |
| Hit rate requires resolution | Can't inflate by avoiding outcomes |
| Brier score penalty | Confident-but-wrong signals hurt |
| Acceptance rate gate | < 10% acceptance → score = 0 |
| Sharpness weighting *(roadmap)* | Timid hedging doesn't accumulate karma |
| Difficulty-adjusted sharpness *(research)* | Bold-on-easy gaming doesn't accumulate karma |

### 6.9 Adversarial Model: Attack Vectors and Mitigations

The system assumes adversarial producers. The following attack vectors have been identified and addressed:

| Attack Vector | Description | Mitigation | Status |
|---------------|-------------|------------|--------|
| **Sybil farming** | Register multiple identities, run parallel strategies, promote the lucky one | Cold-start friction (new producers carry no weight), correlation detection (P4.3 penalizes aligned forecasts), planned: Forge proof-of-work registration | Partial |
| **Bold-on-easy** | Issue high-confidence forecasts only during obvious trends to farm sharpness karma | Difficulty-adjusted sharpness (§4.3) conditions karma on regime base rate | Research |
| **Timid hedging** | Cluster all forecasts near 0.5 to minimize Brier volatility while adding no resolution | Basic sharpness weighting rewards `\|confidence - 0.5\|` | Roadmap |
| **Timing gaming** | Submit forecasts just before horizon close when direction is nearly determined | Minimum horizon enforcement; forecasts within 10% of horizon expiry are rejected | Implemented |
| **Selective resolution** | Avoid resolution on losing forecasts to inflate hit rate | Hit rate computed only from resolved outcomes; unresolved forecasts contribute 0 | Implemented |
| **Spam flooding** | Submit high volume of low-quality signals to dominate by quantity | Volume component uses accepted signals only; acceptance rate gate (< 10% → score 0) | Implemented |
| **Streak manipulation** | Submit one signal per day to build consistency score without quality | Streak counts accepted-signal days only | Implemented |
| **Correlation amplification** | Multiple producers emit identical signals to amplify weight | NoveltyInterpreter (P4.3) penalizes forecasts aligned with existing conviction | Shadow mode |
| **Regime front-running** | Accumulate karma in one regime, carry inflated weight into transition | Regime-conditional karma tables; accelerated decay (α → 0.15) during transitions | Research |
| **Oracle Goodhart** | Optimize against exposed oracle metrics rather than genuine forecasting | Anti-Goodhart header; metrics may change without notice; drift detection planned | Partial |

**Unmitigated vectors (acknowledged risks):**

| Vector | Risk | Planned Mitigation |
|--------|------|-------------------|
| **Collusion** | Multiple producers coordinate to game ensemble patterns | Economic stake requirement; on-chain registration cost |
| **Model theft** | Adversary reverse-engineers successful producer strategies from oracle data | Delay on oracle data freshness; aggregated rather than per-forecast exposure |
| **Sophisticated Sybil** | Adversary runs diverse uncorrelated strategies across Sybil identities | No current mitigation; requires proof-of-humanity or significant stake |

The adversarial model is not complete. New attack vectors will emerge as the system scales. The design philosophy is defense-in-depth: multiple overlapping mitigations, shadow-mode testing before deployment, and explicit acknowledgment of unmitigated risks.

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
| Regime-conditional karma | 100 outcomes per regime | Regime-specific karma tables |

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
- Karma attribution with directional EMA (α=0.05)
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
- Regime-conditional karma (logging, not affecting synthesis)

### 8.2 Implementation Status (beta.8)

| Component | Status |
|-----------|--------|
| 13 domain producers (TradFi, OnChain, TA, Sentiment, Social) | ✅ Implemented |
| Brier score tracking and outcome resolution | ✅ Implemented |
| Karma EMA attribution (α=0.05, directional) | ✅ Implemented |
| LLM critic, regime matrix, prosecutor, self-memory | ✅ Shadow mode only |
| Cross-producer novelty penalty (P4.3) | ✅ Shadow mode only |
| Meta-producer (PerformanceAggregator) | ✅ Activates at 500 outcomes |
| Oracle (verifiable track records) | ✅ Implemented — hash-linked |
| Sharpness weighting on karma | ⚗️ Specified, not deployed |
| Regime-conditional karma decay (HMM) | ⚗️ Research design |
| EAS registration attestation | ⚗️ Roadmap |
| External chain anchoring | ⚗️ Roadmap |
| Fractional Kelly integration | ⚗️ Candidate implementation |

### 8.3 Data Accumulation Timeline

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

### 8.4 Open Problems

**Sybil resistance:** Karma is gameable until registration has non-trivial cost. Planned: Forge-based proof of work or on-chain stake.

**Regime detection:** Current regime tagging is rule-based (BULL/BEAR/TRANSITION/CRISIS). Planned: probabilistic regime model with uncertainty (Hamilton, 1989).

**Calibration curves:** Current Brier score is aggregate. Planned: per-confidence-bucket calibration with isotonic regression for probability mapping.

**Multi-asset correlation:** Current hierarchy penalizes correlated domains but not correlated assets. Planned: cross-asset correlation in synthesis.

**External data quality:** Binance public API fallback is best-effort. Planned: redundant price feeds with median selection.

**Oracle monetization:** Current oracle is a public good. Planned: premium tier with real-time updates, webhooks, and bulk API access.

---

## References

- Gneiting, T. & Raftery, A.E. (2007). Strictly Proper Scoring Rules, Prediction, and Estimation. *JASA* 102(477).

- Goodhart, C.A.E. (1984). "Problems of Monetary Management: The UK Experience." In *Monetary Theory and Practice*, pp. 91-121. Macmillan.

- Hamilton, J.D. (1989). A New Approach to the Economic Analysis of Nonstationary Time Series. *Econometrica* 57(2).

- Kelly, J.L. (1956). A New Interpretation of Information Rate. *Bell System Technical Journal* 35(4).

- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley.

- Popper, K.R. (1959). *The Logic of Scientific Discovery*. Hutchinson. (Originally *Logik der Forschung*, 1934.)

- Tetlock, P. & Gardner, D. (2015). *Superforecasting: The Art and Science of Prediction*. Crown.

---

## Appendix A: Key Source Files

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

## Appendix B: Database Tables

| Table | Purpose |
|-------|---------|
| `events` | Hash-chained event store |
| `forecast_resolution_state` | Idempotent outcome resolution tracking |
| `forecast_calibration` | Per-producer Brier scores |
| `producer_performance` | Rolling producer stats |
| `producer_correlation` | Pairwise producer agreement rates |
| `producer_karma` | EMA karma scores (global) |
| `producer_karma_regime` | Regime-conditional karma scores |
| `signal_stratification` | Confidence band outcome tracking |
| `system_state` | Kill switch and cockpit state |
| `contributors` | Registered contributor identities |
| `karma_intents` | Trade → karma attribution links |

## Appendix C: Configuration Reference

| Parameter | Default | What It Controls |
|-----------|---------|------------------|
| `brain.auto_paper_trade` | `true` | Auto-execute on high confidence |
| `weights.*` | sum to 1.0 | Domain synthesis weights |
| `karma.regime_conditional` | `false` | Enable regime-conditional karma tables |
| `B1E55ED_LLM_CRITIC_SHADOW` | `true` | LLM critic shadow mode |
| `B1E55ED_PROSECUTOR_SHADOW` | `true` | Prosecutor shadow mode |
| `MIN_FORECASTS_FOR_ACTIVATION` | 500 | Meta-producer activation gate |
| `MIN_SAMPLE_FOR_PATTERN` | 10 | Meta-producer pattern threshold |
| `WIN_RATE_THRESHOLD` | 0.60 | Meta-producer win rate gate |

## Appendix D: Glossary

| Term | Definition |
|------|------------|
| **Brier score** | `(confidence - outcome)²` — calibration metric where 0 is perfect |
| **Karma** | Directional EMA reputation score tracking producer contribution to profitable outcomes |
| **PCS** | Position Conviction Score — brain output, 0-100 scale |
| **Redundancy discount** | Confidence penalty for signals that agree with existing consensus |
| **Resolution** | Brier component measuring forecast informativeness vs base rate |
| **Shadow mode** | Layer observes and logs but does not mutate forecasts |
| **Sharpness** | `|confidence - 0.5| × 2` — reward factor for bold forecasts *(specified, not deployed)* |
| **Stratification** | Bucketing signals by confidence for calibration testing |
| **The Forge** | Ethereum vanity address generator for `0xb1e55ed` prefix |

---

*"The system that learns from its own outcomes has a structural advantage over systems that cannot."*

*The code remembers. The hex is blessed: 0xb1e55ed.*
