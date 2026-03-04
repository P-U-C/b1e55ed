# Producer Intelligence Layer

## Overview

The 13 base producers are dumb signal emitters. They collect data, normalize it, and publish events. They have no memory of whether they were right or wrong, no awareness of what other producers are saying, and no ability to adapt to different market regimes.

The Producer Intelligence Layer (P3 + P4) fixes this. It wraps every producer in an interpreter stack that adds:

- **Per-signal adaptations** (P3): regime conditioning, LLM critique, self-memory, adversarial prosecution, novelty filtering
- **System-level intelligence** (P4): hierarchical weighting, multi-horizon forecasts, cross-producer awareness, and a meta-producer that learns from the ensemble's track record

Every layer in the stack defaults to **shadow mode** (`shadow=True`): it observes, logs, and learns — but does not mutate the forecast. This is the right default. You observe before you trust.

---

## Architecture: The Interpreter Stack

Each producer's raw output passes through a layered interpreter chain. Each layer wraps the inner layer, adding one specific capability. The stack is applied automatically by `BaseProducer.emit_forecast()`.

```text
┌─────────────────────────────────────────────────────────┐
│                   NoveltyInterpreter                    │  ← P4.3: cross-producer awareness
│  ┌───────────────────────────────────────────────────┐  │
│  │              ProsecutorInterpreter                │  │  ← P3.5: adversarial counter-case
│  │  ┌─────────────────────────────────────────────┐  │  │
│  │  │           SelfMemoryInterpreter             │  │  │  ← P3.4: karma-based confidence
│  │  │  ┌───────────────────────────────────────┐  │  │  │
│  │  │  │         RegimeInterpreter             │  │  │  │  ← P3.2: regime conditioning
│  │  │  │  (via Interpreter.safe_interpret)     │  │  │  │
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

**Data flow per cycle:**

| Step | Layer | What happens |
|------|-------|--------------|
| 1 | `BaseProducer` | `collect()` → `normalize()` → raw signals |
| 2 | `Interpreter.interpret()` | Rule-based: signals → `ForecastPayload` (action + confidence) |
| 3 | `LLMCriticInterpreter` | LLM reviews candidate; may adjust confidence ±0.3 (shadow default) |
| 4 | `Interpreter.apply_regime_conditioning()` | `RegimeMatrix` scales confidence by regime (BULL/BEAR/CRISIS/TRANSITION) |
| 5 | `SelfMemoryInterpreter` | Brier history adjusts confidence ±max_delta (shadow default) |
| 6 | `ProsecutorInterpreter` | Adversarial LLM builds counter-case; may suppress or boost (shadow default) |
| 7 | `NoveltyInterpreter` | Penalizes agreement with existing brain conviction (shadow default) |
| 8 | Emit | `FORECAST_V1` event written to event store |

**Key invariant:** No layer in the stack ever changes the forecast `action` (long/short/flat). Only `confidence` is modulated, or the forecast is replaced with an abstention.

---

## P3: Per-Signal Adaptations

### P3.1 — LLM Critic (shadow mode)

**What it does:** An LLM reviews the rule-engine's candidate forecast and flags mis-calibrated confidence or signals that should be suppressed.

**How it works:**
1. The rule engine produces a candidate `ForecastPayload` (action + confidence)
2. The LLM sees: the candidate, the top 5 raw signals, the regime tag, trailing Brier score, and aggregate conviction
3. The LLM returns a `confidence_delta` (±0.3 max) and optionally `suppress=True`
4. In shadow mode: the critique is hashed into `reasoning_hash` and logged to `llm_shadow_log` but the candidate is returned unchanged
5. In live mode: confidence is adjusted, regime caps applied, and suppressed forecasts become abstentions

**Shadow mode** (`shadow=True`, the default):
- Critique is computed and stored but does not affect the output
- Logged to `llm_shadow_log` table for later analysis
- Use `get_shadow_comparison()` to see rule-vs-LLM divergence stats

**Meta-guardrail:** If the producer's trailing Brier score exceeds `0.35`, the LLM critic automatically reverts to shadow mode for that cycle — even if live mode is configured. This prevents a struggling producer from compounding errors with LLM adjustments.

**Confidence bounds in live mode:**
- Delta clamped to `[-0.3, +0.3]`
- Regime cap applied (BULL: 1.0, BEAR: 0.7, TRANSITION: 0.6, CRISIS: 0.4)
- Minimum `0.3` confidence required after adjustment (`min_live_confidence`)

**Configuration (env vars):**

| Variable | Default | What it does |
|----------|---------|--------------|
| `B1E55ED_LLM_CRITIC_ENABLED` | `false` | Enable/disable the critic |
| `B1E55ED_LLM_CRITIC_URL` | `https://api.openai.com/v1` | LLM API endpoint |
| `B1E55ED_LLM_CRITIC_KEY` | (none) | API key (falls back to `OPENAI_API_KEY`) |
| `B1E55ED_LLM_CRITIC_MODEL` | `gpt-4o-mini` | Model to use |
| `B1E55ED_LLM_CRITIC_TIMEOUT_S` | `8.0` | Request timeout |
| `B1E55ED_LLM_CRITIC_SHADOW` | `true` | Shadow mode (observe only) |

**Graceful degradation:** If the LLM is unconfigured, returns an error, or times out — the rule-engine's candidate is returned unchanged. The critic never blocks emission.

---

### P3.2 — Regime Matrix

**What it does:** Conditions every forecast on the current market regime. Different regimes get different confidence scaling, different minimum thresholds, and optionally full abstention.

**How it works:**
- Each producer can declare a `RegimeMatrix` on its interpreter class
- After `interpret()` returns a candidate, `apply_regime_conditioning()` applies the regime-specific `RegimeConfig`
- This happens automatically inside `safe_interpret()` — producers don't need to add if/else blocks

**RegimeConfig fields:**

| Field | Type | Default | What it does |
|-------|------|---------|--------------|
| `confidence_multiplier` | `float` | `1.0` | Scale candidate confidence (0.5 = halve, 1.2 = boost 20%) |
| `abstain` | `bool` | `False` | Always abstain in this regime (overrides multiplier) |
| `active_rules` | `frozenset[str] \| None` | `None` | Which named rule groups run; `None` = all, empty = implicit abstain |
| `min_confidence` | `float \| None` | `None` | Minimum confidence to emit; `None` = use interpreter default (0.1) |

**Global regime confidence caps** (from `engine/core/regime.py`, 0-10 scale → divided by 10 at use):

| Regime | Cap (0-10) | Effective cap (0-1) |
|--------|-----------|---------------------|
| `BULL` | 10.0 | 1.00 |
| `BEAR` | 7.0 | 0.70 |
| `TRANSITION` | 6.0 | 0.60 |
| `CRISIS` | 4.0 | 0.40 |

**Example declaration:**

```python
regime_matrix = RegimeMatrix(
    configs={
        "BULL": RegimeConfig(confidence_multiplier=1.1),
        "BEAR": RegimeConfig(confidence_multiplier=0.7, min_confidence=0.5),
        "CRISIS": RegimeConfig(abstain=True),
        "TRANSITION": RegimeConfig(confidence_multiplier=0.85),
    }
)
```

**When no `RegimeMatrix` is set:** The interpreter's output passes through unchanged (the default for producers that haven't declared regime-specific behavior).

---

### P3.3 — Differentiated Inputs

Each domain producer receives signals specific to its domain. This is handled at the `collect()` + `normalize()` level — each producer ingests only what it knows how to interpret.

| Domain | Unique inputs | Why it matters |
|--------|--------------|----------------|
| onchain | Whale netflow, exchange flows, stablecoin supply, liquidation clusters | Flow regimes that TradFi producers can't see |
| tradfi | CME basis, funding rates, OI changes, ETF flows | Carry/basis dynamics invisible to on-chain |
| technical | RSI, EMA structure, orderbook depth, bid/ask imbalance | Microstructure that fundamentals-based producers ignore |
| social | CT sentiment, narrative scores, contrarian/echo-chamber flags | Reflexive social dynamics |
| events | Catalyst list, headline sentiment, impact scores | Discrete shocks vs continuous signals |
| curator | Operator thesis, conviction, rationale | Human edge that no automated feed captures |

The intelligence layer doesn't change what each producer ingests — it changes how the system evaluates and combines the resulting forecasts.

---

### P3.4 — Producer Self-Memory

**What it does:** Adjusts a producer's confidence based on its own historical Brier score. Good calibration → confidence boost. Poor calibration → confidence penalty. A grimoire with teeth: lessons persist because they're callable.

**How it works:**
1. `SelfMemory.query()` reads from `forecast_calibration` (Brier scores, regime breakdown)
2. Computes a blended delta from long-term (90-day) and recent (3-day) Brier performance
3. Optional regime-specific adjustment (20% weight if ≥3 regime-specific samples)
4. `SelfMemoryInterpreter` applies the delta to the candidate's confidence

**Brier → delta mapping:**

| Brier score | Confidence delta | Interpretation |
|-------------|-----------------|----------------|
| ≤ 0.10 | +0.15 | Excellent calibration |
| ≤ 0.20 | +0.08 | Good calibration |
| ≤ 0.25 | 0.00 | Neutral (baseline) |
| ≤ 0.33 | -0.10 | Poor calibration |
| > 0.33 | -0.20 | Bad calibration |

**Blending formula:**
```
blended = (1 - streak_weight) × long_term_delta + streak_weight × recent_delta
```
Where `streak_weight = 0.35` by default (recent performance gets 35% influence).

**Guardrails:**
- `max_delta = ±0.30` — confidence can never shift more than 30% in either direction
- `min_resolved = 5` — no adjustment until ≥5 resolved forecasts exist
- Action is never changed (confidence only)
- Returns no-op when DB is unavailable

**SelfMemoryConfig defaults:**

| Field | Default | What it controls |
|-------|---------|-----------------|
| `enabled` | `True` | Enable/disable self-memory |
| `min_resolved` | `5` | Minimum resolved forecasts before activation |
| `max_delta` | `0.30` | Maximum confidence adjustment |
| `streak_window_days` | `3` | Recent performance window |
| `long_window_days` | `90` | Long-term performance window |
| `streak_weight` | `0.35` | Weight of recent vs long-term |

---

### P3.5 — Adversarial Prosecutor

**What it does:** An LLM constructs the strongest possible case AGAINST each forecast. If the bear case overwhelms the bull case, the forecast is suppressed. If the bear case is weak, confidence gets a small boost.

**How it works:**
1. The prosecutor sees: the candidate forecast, top 5 signals, and regime tag
2. It returns:
   - `bear_strength` (0.0-1.0): strength of the counter-case
   - `bull_strength` (0.0-1.0): strength of the thesis from the data
   - `suppress` (bool): True if bear_strength > bull_strength by more than 0.15
   - `confidence_boost` (0.0-0.15): bonus if bear case is weak (bear_strength < 0.25)
   - `rationale`: one-sentence reason
3. In shadow mode: result is logged but the candidate passes through unchanged
4. In live mode: suppress → abstain, confidence_boost → bounded adjustment

**Why it matters:** Catches correlated inputs — when all signals agree because they're measuring the same thing from different angles, the prosecutor finds the shared assumption.

**Configuration (env vars):**

| Variable | Default | What it does |
|----------|---------|--------------|
| `B1E55ED_PROSECUTOR_ENABLED` | `false` | Enable/disable prosecutor |
| `B1E55ED_PROSECUTOR_URL` | `https://api.openai.com/v1` | LLM API endpoint |
| `B1E55ED_PROSECUTOR_KEY` | (none) | API key (falls back to `OPENAI_API_KEY`) |
| `B1E55ED_PROSECUTOR_MODEL` | `gpt-4o-mini` | Model to use |
| `B1E55ED_PROSECUTOR_TIMEOUT_S` | `8.0` | Request timeout |
| `B1E55ED_PROSECUTOR_SHADOW` | `true` | Shadow mode (observe only) |

**Graceful degradation:** If the prosecutor is unconfigured, returns an error, or times out — the candidate passes through unchanged. The `ProsecutorInterpreter` also respects `prosecutor.config.shadow` as an additional shadow check.

---

## P4: System-Level Intelligence

### P4.1 — Hierarchical Weighting

**What it does:** Dynamically adjusts per-domain weights in synthesis based on historical performance, asset fit, regime fit, and cross-domain correlation.

**The multiplier chain:**

The `HierarchyEngine` computes a weight multiplier for each domain per cycle. The multiplier modulates the domain's prior weight (from config) during brain synthesis.

```text
final_multiplier = weighted_blend(
    0.40 × producer_reliability,   # trailing Brier (regime-aware)
    0.25 × asset_fit,              # per-asset historical Brier
    0.25 × regime_fit,             # domain performance in current regime
    0.10 × (1.0 - correlation_penalty)  # penalty for correlated domains
)
```

**Factor details:**

| Factor | Weight | What it measures | Data source |
|--------|--------|-----------------|-------------|
| `producer_reliability` | 40% | Rolling Brier score, blended 70/30 with regime-specific Brier | `forecast_calibration` table |
| `asset_fit` | 25% | 60-day Brier for this specific asset | `forecast_calibration` table |
| `regime_fit` | 25% | Brier in the current regime (BULL/BEAR/etc) | `forecast_calibration` table |
| `correlation_penalty` | 10% | Max pairwise correlation with other domains (×0.5) | `producer_correlation` table |

**Brier → multiplier conversion:**

| Brier score | Multiplier |
|-------------|-----------|
| ≤ 0.10 | 1.50 |
| ≤ 0.20 | 1.30 |
| ≤ 0.25 | 1.00 |
| ≤ 0.30 | 0.85 |
| > 0.30 | 0.70 |

**Guardrails:**
- `MIN_MULTIPLIER = 0.1` — a domain can lose at most 90% of its prior weight
- `MAX_MULTIPLIER = 2.0` — a domain can at most double its prior weight
- `MIN_BRIER_SAMPLES = 5` — no reliability adjustment until ≥5 resolved forecasts
- `MIN_ASSET_SAMPLES = 3` — no asset_fit adjustment until ≥3 per-asset samples
- All factors return `1.0` (neutral) when data is insufficient

**Graceful degradation:** When tables are empty or P2.x data is unavailable, all multipliers return 1.0 and domain priors from config apply unchanged.

---

### P4.2 — Multi-Horizon Forecasts

**What it does:** Each domain produces forecasts at domain-appropriate horizons with horizon-specific confidence scaling.

**Design principle:** Short horizons are noisier → lower confidence cap. Long horizons are less actionable but carry higher conviction when signals agree.

**Domain-specific horizon sets:**

| Domain | Horizons | Confidence scale | Confidence cap |
|--------|----------|-----------------|----------------|
| **TECHNICAL** | 4h | 1.00 | 0.85 |
| | 24h | 0.90 | 0.80 |
| **TRADFI** | 4h | 1.00 | 0.85 |
| | 24h | 1.05 | 0.88 |
| | 3d | 0.95 | 0.82 |
| **ONCHAIN** | 4h | 0.90 | 0.80 |
| | 24h | 1.00 | 0.85 |
| | 3d | 1.10 | 0.88 |
| **SENTIMENT** | 4h | 0.85 | 0.75 |
| | 24h | 1.00 | 0.82 |
| **DEFAULT** | 4h | 1.00 | 0.85 |

**How horizon scaling works:**

```python
scaled_confidence = base_confidence × confidence_scale
final_confidence = min(scaled_confidence, confidence_cap)
```

Note that TradFi gets a slight 24h boost (`scale=1.05`) because basis/funding signals are more meaningful over 24h. On-chain gets a 3d boost (`scale=1.10`) because accumulation/distribution patterns play out over days.

---

### P4.3 — Cross-Producer Awareness

**What it does:** Gives each producer a single aggregate signal about what the rest of the system is thinking, without revealing individual producer identities or domain breakdowns.

**Aggregate conviction:**
- `ConvictionStateReader` reads recent `FORECAST_V1` events (default: last 2 hours)
- For each asset: weighted average of `(confidence × direction_sign)` across all producers
  - `long = +1`, `short = -1`, `flat/no_forecast = 0`
- Result: a single signed float in `[-1, +1]` (positive = bullish, negative = bearish)
- Minimum 2 forecasts required for a non-zero signal

**Novelty penalty mechanics:**
- High agreement with strong conviction → suppress confidence (you're adding noise, not signal)
- Contrarian signal → slight confidence boost (disagreement = information)
- Weak conviction → no penalty (brain is uncertain, all signals valuable)

**Tuning constants (from `engine/core/novelty.py`):**

| Constant | Value | What it controls |
|----------|-------|-----------------|
| `NOVELTY_CONVICTION_THRESHOLD` | `0.5` | Minimum brain conviction strength to trigger any novelty adjustment |
| `NOVELTY_AGREEMENT_PENALTY` | `0.15` | Max penalty multiplier when agreeing with strong conviction |
| `NOVELTY_CONTRARIAN_BOOST` | `0.05` | Max boost multiplier when disagreeing with strong conviction |
| `NOVELTY_MIN_CONFIDENCE` | `0.1` | Floor — confidence never drops below this |

**Decision rules:**

| Condition | Result |
|-----------|--------|
| `agreement > 0.3` and conviction strong | Penalty: `−0.15 × agreement × conviction_strength` |
| `agreement < −0.3` and conviction strong | Boost: `+0.05 × |agreement| × conviction_strength` |
| Conviction weak (`< 0.5`) | No adjustment |
| Neutral agreement (`−0.3 to +0.3`) | No adjustment |

**Shadow mode** (`shadow=True`, the default): The novelty result is logged but the candidate passes through unchanged. Action is **never** changed — only confidence is modulated.

---

### P4.4 — The Meta-Producer

The meta-producer is the system's compound learning output. It learns from the ensemble's historical track record and emits forecasts based on ensemble pattern matching.

#### Outcome Resolver

**What it does:** Resolves elapsed `FORECAST_V1` events against actual prices, producing `FORECAST_OUTCOME_V1` events. This is the data collection mechanism that feeds everything downstream.

**How it works:**
1. Finds unresolved `FORECAST_V1` events whose horizon has elapsed (+ 5-minute buffer)
2. Fetches prices at forecast time and resolution time:
   - First: local `price_history` table (seconds and milliseconds epoch)
   - Fallback: Binance public klines API
3. Computes: `return_actual_pct`, `direction_correct`, `brier_score`
4. Writes `FORECAST_OUTCOME_V1` event (immutable, deduplicated)
5. Records resolution in `forecast_resolution_state` table (idempotent)

**How to run:**

```bash
b1e55ed resolve-outcomes
```

Returns the count of forecasts resolved. Exit code is always 0.

**Cron setup:**

```
*/30 * * * * /usr/local/bin/b1e55ed resolve-outcomes >> /var/log/b1e55ed/resolver.log 2>&1
```

Run every 30 minutes. Idempotent — safe to run as often as you want.

**What to expect in logs:**
- `outcome_resolver_missing_price` — price data unavailable for a forecast (normal early on)
- Normal output: count of resolved forecasts per run

#### Performance Aggregator

**What it does:** Computes rolling producer performance statistics from `FORECAST_OUTCOME_V1` history.

**Outputs:**
- `producer_performance` table: per-producer, per-asset, per-horizon, per-regime stats (win_rate, avg_brier, avg_confidence, confidence_reliability)
- `producer_correlation` table: pairwise producer agreement rates, agreement win rates, disagreement win rates

**Minimum data:** `MIN_FORECASTS_FOR_STATS = 5` resolved outcomes per group.

#### MetaProducer

**What it does:** Reads performance tables and learns which ensemble patterns historically lead to correct outcomes.

**Hard constraint:** No direct market data reads. Inputs are restricted to:
- `FORECAST_V1` events (current ensemble state)
- `FORECAST_OUTCOME_V1` events (historical outcomes)
- `producer_performance` / `producer_correlation` (derived tables)

**Activation gate:** `MIN_FORECASTS_FOR_ACTIVATION = 500` resolved outcomes must exist before the meta-producer emits any non-abstention forecast. Below this threshold, it always abstains with `INSUFFICIENT_DATA`.

**Pattern matching:**
1. Gets current ensemble state: latest action (long/short/flat) per producer for the target asset (last 2 hours)
2. Searches historical episodes for matching ensemble patterns
3. Computes win rate and majority direction from matching episodes
4. Emits a forecast only if:
   - `n ≥ MIN_SAMPLE_FOR_PATTERN` (10 matching episodes)
   - `win_rate ≥ WIN_RATE_THRESHOLD` (0.60)

**Shadow mode** (`shadow=True`, the default): Even after activation, the meta-producer logs its would-be forecast but emits an abstention with `SHADOW_MODE` reason. This ensures the pattern library matures before affecting synthesis.

**Registration:** `@register("meta", domain="events")` — runs on `*/30 * * * *` schedule.

---

## Configuration

### Per-layer configuration summary

| Layer | Config mechanism | Shadow default | Key knobs |
|-------|-----------------|----------------|-----------|
| **LLM Critic** | Env vars (`B1E55ED_LLM_CRITIC_*`) | `shadow=True` | `ENABLED`, `MODEL`, `SHADOW` |
| **Regime Matrix** | Python class attribute | N/A (always active if declared) | `RegimeConfig` per regime |
| **Self-Memory** | `SelfMemoryConfig` dataclass | `enabled=True` (always applies) | `max_delta`, `min_resolved`, `streak_weight` |
| **Prosecutor** | Env vars (`B1E55ED_PROSECUTOR_*`) | `shadow=True` | `ENABLED`, `MODEL`, `SHADOW` |
| **Novelty** | Constructor args | `shadow=True` | `lookback_minutes` (default: 120) |
| **Hierarchy** | Constants in `hierarchy.py` | N/A (always active) | Factor weights, min sample counts |
| **Meta-Producer** | Constructor arg + constants | `shadow=True` | `MIN_FORECASTS_FOR_ACTIVATION` (500) |

### When to change defaults

**Enable LLM Critic live mode** when:
- You've run shadow mode for ≥2 weeks
- `get_shadow_comparison()` shows the LLM consistently improves calibration
- You've verified the LLM isn't just agreeing with the rule engine (check suppression rate)

**Enable Prosecutor live mode** when:
- Shadow logs show meaningful bear/bull strength separation
- The prosecutor catches genuine correlated-input problems
- Suppression rate is reasonable (not suppressing everything)

**Enable Novelty live mode** when:
- You have ≥3 producers running and brain conviction is meaningful
- You want to actively penalize redundant signals

**Enable Meta-Producer live mode** when:
- ≥500 resolved outcomes exist
- Pattern library shows win_rate ≥ 0.60 on ≥10 matching episodes
- You've verified shadow logs look sensible for ≥1 month

---

## Shadow Mode

Shadow mode is the most important design pattern in the intelligence layer. Every LLM-based and adaptive layer defaults to `shadow=True`.

**What shadow mode means operationally:**
- The layer runs its full computation (LLM call, novelty penalty, pattern match, etc.)
- The result is logged to the database or structured log
- The candidate forecast passes through **unchanged**
- No forecast is ever suppressed, boosted, or modified by a shadow layer

**Why this is the right default:**
- New layers have no track record. Trusting them immediately is reckless.
- Shadow data lets you compare "what would have happened" against actual outcomes.
- You can validate each layer independently before going live.
- If an LLM starts hallucinating or a pattern goes wrong, shadow mode means zero production impact.

**How to enable live mode:**
- LLM Critic: set `B1E55ED_LLM_CRITIC_SHADOW=false`
- Prosecutor: set `B1E55ED_PROSECUTOR_SHADOW=false`
- Novelty: pass `shadow=False` to `NoveltyInterpreter` constructor
- Meta-Producer: pass `shadow=False` to `MetaProducer` constructor

**Observation tools:**
- `get_shadow_comparison(db, producer, days=30)` — LLM critic shadow stats (rule vs adjusted confidence, suppression rate, error rate)
- `llm_shadow_log` table — raw per-cycle LLM critic logs
- Producer logs at INFO level — self-memory, prosecutor, novelty all log their shadow results

---

## Cron Setup

### Outcome Resolver

The outcome resolver must run periodically to collect the data that feeds the entire intelligence layer.

```
*/30 * * * * /usr/local/bin/b1e55ed resolve-outcomes >> /var/log/b1e55ed/resolver.log 2>&1
```

**Verify it's running:**

```bash
# Check recent outcomes
sqlite3 data/brain.db "SELECT COUNT(*) FROM events WHERE type = 'FORECAST_OUTCOME_V1'"

# Check resolution state
sqlite3 data/brain.db "SELECT COUNT(*) FROM forecast_resolution_state"

# Check for unresolved forecasts older than their horizon
sqlite3 data/brain.db "
  SELECT COUNT(*) FROM events e
  LEFT JOIN forecast_resolution_state rs ON rs.forecast_event_id = e.id
  WHERE e.type = 'FORECAST_V1'
    AND rs.forecast_event_id IS NULL
"
```

---

## Data Activation Timeline

The intelligence layer activates progressively as data accumulates:

```text
Day 1       Outcome resolver starts collecting.
            All layers in shadow mode. System behaves identically to pre-P3/P4.

Week 1      Self-memory activates for producers with ≥5 resolved forecasts.
            Small confidence adjustments begin (max ±0.30).

Week 2-4    ~500 outcomes accumulate (activation threshold).
            MetaProducer begins logging shadow forecasts.
            Hierarchy engine starts adjusting domain multipliers.

Month 2     Shadow logs have enough data to evaluate LLM critic performance.
            Operator can review get_shadow_comparison() and decide on live mode.

Month 3     Regime-conditional stats become reliable (enough samples per regime).
            Hierarchy regime_fit factor becomes meaningful.

Month 6     Full ensemble pattern library.
            MetaProducer has deep history across multiple regime transitions.
            All layers can be evaluated for live mode promotion.
```

| Milestone | Data needed | What activates |
|-----------|-------------|----------------|
| Self-memory | 5 resolved forecasts per producer | Confidence ± Brier delta |
| Hierarchy reliability | 5 resolved forecasts per domain | Domain weight multipliers |
| Hierarchy asset_fit | 3 per-asset resolved forecasts | Asset-specific multipliers |
| MetaProducer shadow | 500 total resolved outcomes | Pattern logging begins |
| MetaProducer live | 500 outcomes + 10 matching episodes + 60% win rate | Live ensemble forecasts |
| Full regime stats | ~50+ per regime | Regime-conditional everything |

---

## Reference: Source Files

| File | What it contains |
|------|-----------------|
| `engine/core/interpreter.py` | `Interpreter`, `LLMCriticInterpreter`, `SelfMemoryInterpreter`, `ProsecutorInterpreter`, `NoveltyInterpreter` |
| `engine/core/regime.py` | `RegimeMatrix`, `RegimeConfig`, `REGIME_CAPS` |
| `engine/core/prosecutor.py` | `Prosecutor`, `ProsecutorConfig`, `ProsecutionResult` |
| `engine/core/novelty.py` | `compute_novelty_penalty`, `NoveltyResult` |
| `engine/core/self_memory.py` | `SelfMemory`, `SelfMemoryConfig`, `SelfMemoryResult` |
| `engine/core/llm_critic.py` | `LLMCritic`, `LLMCriticConfig`, `CritiqueResult` |
| `engine/core/horizons.py` | `HorizonConfig`, domain horizon sets, `apply_horizon_config` |
| `engine/brain/hierarchy.py` | `HierarchyEngine`, `HierarchyFactors`, `HierarchyResult` |
| `engine/brain/conviction_state.py` | `ConvictionStateReader`, `ConvictionState` |
| `engine/brain/outcome_resolver.py` | `OutcomeResolver`, `run_resolver` |
| `engine/brain/performance_aggregator.py` | `PerformanceAggregator` |
| `engine/brain/calibration.py` | `brier_summary`, `register_forecast`, `resolve_forecast`, `log_shadow_critique` |
| `engine/producers/meta.py` | `MetaProducer` |
