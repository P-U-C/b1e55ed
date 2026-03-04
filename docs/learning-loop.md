# Learning Loop

> Compound learning is the moat.

This document specifies b1e55ed’s compound learning engine: how it attributes
outcomes, adjusts synthesis weights, scores producers, and feeds results back
into the corpus.

## Thesis

A trading system that does not learn from its own outcomes is a static tool.

The learning loop turns every closed position into training data.

Module motto:

> "The system that learns from its own outcomes will outperform systems that don't."

## Components

### 1) Outcome attribution (per-trade / daily)

**Goal**: match a closed position back to the **conviction score** that opened it.

**Inputs**
- `positions` row (id, opened_at, closed_at, realized_pnl, conviction_id, regime_at_entry, max_drawdown_during)
- `conviction_scores` row (`id = positions.conviction_id`)
- `conviction_log` rows (`cycle_id + symbol`) capturing domain scores at entry

**Outputs**
- Update `conviction_scores.outcome` and `conviction_scores.outcome_ts`
- Emit `learning.outcome.v1` event

**Metrics written**
- `realized_pnl`
- `time_held_hours`
- `max_drawdown_pct`
- `direction_correct` (derived from PnL sign)
- `regime_at_entry`
- `domain_scores_at_entry` (domain → score)

### 2) Domain weight adjustment (weekly/monthly)

**Goal**: nudge synthesis weights toward domains that predicted better outcomes.

**Window**: rolling 30 days (`ADJUSTMENT_WINDOW_DAYS = 30`).

**Observation threshold**: no adjustment unless at least 20 closed positions
(`MIN_OBSERVATIONS = 20`).

**Safety constraints**
- `MAX_WEIGHT_DELTA = 0.02` (±2% per cycle)
- `MIN_DOMAIN_WEIGHT = 0.05` (5% floor)
- `MAX_DOMAIN_WEIGHT = 0.40` (40% ceiling)

**Algorithm (v1)**
1. For each closed position in the window, compute outcome sign `y ∈ {+1, -1}` from `realized_pnl`.
2. Pull domain scores at entry from `conviction_log` for the score’s `cycle_id` and `symbol`.
3. For each domain, compute correlation between domain score and outcome sign.
4. Translate correlation → delta (scaled, clamped to ±MAX_WEIGHT_DELTA).
5. Clamp to floor/ceiling and renormalize to sum to 1.0.
6. Persist to `data/learned_weights.yaml` and record in `learning_weights`.

### 3) Producer scoring

**Goal**: track which producers are reliable.

Producer scoring is designed to evolve. In the current implementation, the
system stores producer health in `producer_health` and emits a conservative
scoring summary based on staleness and error rate.

Constraints
- No adjustments until at least 20 observations.

### 3b) Producer karma (flywheel)

**Goal**: close the attribution loop with per-producer outcome tracking.

When a position closes:

1. `attribute_outcome()` retrieves all `SIGNAL_ACCEPTED_V1` events linked to the trade
2. Each contributing producer receives an EMA karma update (α = 0.05):
   `karma_new = karma_old × 0.95 + outcome × 0.05`
3. Results stored in `producer_karma` table
4. `ATTRIBUTION_OUTCOME_V1` event emitted

Phase 0: equal weights across contributing producers. Positive outcomes applied immediately; negative outcomes tracked but dampened.

Karma starts at 1.0 for all new producers.

**Files**: `engine/execution/karma.py`, `engine/integration/outcome_writer.py`

### 4) Corpus feedback

**Goal**: update patterns and skills based on realized outcomes.

- Pattern outcomes are tracked in `pattern_matches` (when pattern matching is wired).
- Skill lifecycle is file-based in `corpus/skills/`.

Lifecycle rules (initial)
- Pending skill promoted to active when `score >= 3`
- Active skill archived when `score <= -3`

Skill score storage
- A `score: <int>` line in the first ~40 lines of the markdown file.

## Cold start behavior

- First 30 days: observe only. No weight adjustments.
  - Quote: "Patience is not inaction. It is intelligent waiting."
- 30–90 days: warm period. Adjustments are allowed, but `MAX_WEIGHT_DELTA` is halved to ±1%.
- 90+ days: full adjustments active (±2%).

## Overfitting protection

The system tracks rolling performance around adjustments.

If **3 consecutive cycles** degrade performance, weights are reverted to preset
defaults.

- Quote: "The market rewards adaptation. It punishes curve-fitting."
- Reversion quote: "Sometimes the wisest adjustment is to undo the last one."

## Operator review

Weekly/monthly adjustments are stored in the database (`learning_weights`) and
persisted as an overlay YAML file (`data/learned_weights.yaml`).

Operators can:
- inspect the change history
- delete the overlay file to revert immediately
- approve/reject changes once the approval UI is implemented

## Forecast-Level Learning (P4)

The learning loop above operates at the position/trade level. The P4 intelligence layer adds a parallel forecast-level learning loop that works at higher resolution.

### Outcome Resolver

The outcome resolver is the data collection mechanism for the forecast-level loop. It runs every 30 minutes via cron and resolves elapsed `FORECAST_V1` events against actual prices.

**What it produces:** `FORECAST_OUTCOME_V1` events containing:
- `forecast_event_id` — link to the original forecast
- `producer_id` — which producer made the call
- `direction_correct` — was the direction right?
- `brier_score` — `(confidence - outcome)²` calibration metric
- `return_actual_pct` — actual price change
- `regime_at_forecast` — what regime was active

**Idempotency:** Each forecast can only be resolved once (tracked via `forecast_resolution_state` table). Safe to run repeatedly.

**Price sources:** Local `price_history` table first, Binance public klines API as fallback.

**How to run:**
```bash
b1e55ed resolve-outcomes
```

**Cron setup:**
```
*/30 * * * * /usr/local/bin/b1e55ed resolve-outcomes >> /var/log/b1e55ed/resolver.log 2>&1
```

### Performance Aggregator

The performance aggregator computes rolling statistics from `FORECAST_OUTCOME_V1` events:

- **`producer_performance` table:** Per-producer win rates, average Brier scores, average confidence, and confidence-outcome correlation — grouped by asset, horizon, and regime.
- **`producer_correlation` table:** Pairwise agreement rates between producers, including agreement/disagreement win rates and sample counts.

These tables feed the hierarchical weighting engine (P4.1) and the meta-producer (P4.4). Minimum threshold: 5 resolved outcomes per group.

### MetaProducer

The meta-producer is the learning loop's output layer. It reads only from performance tables and `FORECAST_OUTCOME_V1` history — never from raw market data.

**What it learns:** Which ensemble patterns (combination of producer calls) historically led to correct outcomes. When the current ensemble state matches a historically successful pattern, it emits a forecast with the pattern's win rate as confidence.

**Activation gate:** 500 resolved outcomes must exist before the meta-producer emits any non-abstention forecast (`MIN_FORECASTS_FOR_ACTIVATION = 500`). Below this, it always abstains.

**Shadow mode:** Even after activation, the meta-producer defaults to `shadow=True` — it logs what it would have emitted but produces abstentions. This ensures the pattern library matures before affecting synthesis.

**The full learning chain:**
```text
FORECAST_V1 → (horizon elapses) → OutcomeResolver → FORECAST_OUTCOME_V1
    → PerformanceAggregator → producer_performance + producer_correlation
    → MetaProducer (pattern matching) → FORECAST_V1 (meta ensemble signal)
```

For full details on the interpreter stack and activation timeline, see [producer-intelligence.md](producer-intelligence.md).

## Files

- `engine/brain/learning.py` — learning engine
- `engine/integration/outcome_writer.py` — writes outcomes when positions close
- `engine/integration/learning_loop.py` — cadence scheduling + persistence glue
- `engine/brain/outcome_resolver.py` — forecast outcome resolver (P4)
- `engine/brain/performance_aggregator.py` — rolling producer stats (P4)
- `engine/producers/meta.py` — meta-producer / ensemble pattern learner (P4)
- `data/learned_weights.yaml` — learned weights overlay (auto-generated)

## Tests

- `tests/unit/test_learning.py`
- `tests/unit/test_learning_weights.py`
- `tests/unit/test_learning_corpus.py`
- `tests/integration/test_learning_e2e.py`
