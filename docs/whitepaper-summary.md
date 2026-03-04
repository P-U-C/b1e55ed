# b1e55ed: A Falsifiable Trading Intelligence Engine

**March 2026**

---

## Abstract

The decisive test: do forecasts assigned higher confidence produce better realized economic outcomes than lower-confidence forecasts, net of fees, under identical execution assumptions?

Trading systems claim edge but cannot prove it. The problem is structural: without closed attribution between signals and outcomes, skill cannot be separated from luck. b1e55ed solves this by making every forecast a falsifiable, immutable probability statement. Each forecast carries direction, confidence, horizon, and producer attribution. Outcomes are resolved against realized prices. Resolution produces a Brier score for every producer, every cycle. Those scores feed back into calibration and domain weights. The loop closes.

---

## 1. Introduction

Every trading system faces the same accountability gap.

A fund reports 40% annual returns. A signal service claims 73% accuracy. A quantitative strategy backtests to a Sharpe of 2.1.

These claims share a defect: they are not falsifiable in the Popperian sense. The reported P&L is an aggregate number. The underlying attribution—which signals contributed to which trades, whether stated confidence matched realized accuracy, whether the system had genuine edge or merely caught a favorable regime—remains opaque.

This opacity is not a disclosure problem. It is a structural one.

Without verifiable attribution, there is no closed feedback loop. Without a closed feedback loop, the system cannot learn from its own outcomes. Without learning, the system runs the same static process forever, with no mechanism for systematic improvement.

b1e55ed closes the loop.

---

## 2. The Attribution Problem

Consider a concrete case.

A trade opens. BTC long, 1% of portfolio, confidence 0.68. Forty-eight hours later, the position closes at +$800.

Questions that should be answerable:

1. Which signals contributed to this trade?
2. Were those signals directionally correct?
3. Did the stated confidence (0.68) reflect realized accuracy across similar signals?
4. Should those signal sources be weighted more or less in future synthesis?

In a traditional system, none of these questions have determinate answers. The P&L is recorded. The attribution is lost. The next trade proceeds with the same weights, the same confidence calibration, the same process—whether or not the system has edge.

b1e55ed makes attribution structural.

---

## 3. The b1e55ed Mechanism

### 3.1 Forecasts as Immutable Probability Statements

Every signal source in b1e55ed emits forecasts with a fixed schema:

- **Direction**: long, short, or flat
- **Confidence**: a probability between 0 and 1
- **Horizon**: the time window over which the forecast applies
- **Producer ID**: the source of the forecast

A producer's confidence value is its stated probability that the following canonical event will resolve as true: the forecast's target asset will close above (for LONG) or below (for SHORT) its entry reference price after horizon H, net of execution fees. This is the event the Brier score evaluates.

Forecasts are written to an append-only, hash-linked event store. Each event references the hash of the prior event, making retroactive modification detectable. Within the current architecture, modification of past events would require recomputing the full hash chain from the point of tampering — detectable on any replay.

### 3.2 Resolution Against Realized Prices

When a forecast's horizon elapses, an outcome resolver compares the predicted direction against actual price movement.

The resolver computes:

- **Direction correctness**: did price move in the predicted direction?
- **Brier score**: (confidence − outcome)², where outcome is 1 if correct, 0 if incorrect

The Brier score is a proper scoring rule (Gneiting & Raftery, 2007). It penalizes overconfidence and underconfidence symmetrically. A forecaster who says "70% confident" should be correct 70% of the time across many forecasts. The Brier score captures both calibration and resolution.

### 3.3 Karma as Producer Weight

Each signal producer accumulates a karma score based on resolved outcomes.

When a position closes:

1. The system retrieves all signals that contributed to the trade
2. For each contributing producer, it computes an outcome value: +1 for correct direction, −1 for incorrect
3. Karma updates via exponential moving average: `karma_new = karma_old × 0.95 + outcome × 0.05`

This is the core karma mechanism: a lightweight directional EMA tracker with α = 0.05. A producer who has been consistently correct will have high karma. A producer who has been consistently wrong will have low karma. A producer who has been random will drift toward neutral.

Karma and Brier score serve different purposes. Brier score measures calibration quality — whether stated probabilities match realized frequencies. Karma is an operational weighting signal — it determines how much a producer's current forecasts influence synthesis. Both metrics must be healthy for a producer to be trusted.

### 3.4 The Sharpness Incentive

A producer can minimize Brier volatility by emitting low-conviction forecasts near the base rate. Such forecasts may appear modestly well-calibrated while adding little resolution or economic value — technically passing calibration checks while contributing no edge. The sharpness incentive addresses this by weighting karma updates by forecast informativeness: `resolution_factor = |confidence - 0.5| × 2`. This design is under evaluation; it requires a calibration quality gate to prevent the opposite failure mode — producers chasing resolution by submitting overconfident forecasts that degrade calibration quality.

This reward structure is gated: sharpness multipliers apply only to producers who meet a minimum historical calibration threshold, preventing overconfident forecasts from accruing disproportionate weight. Without this gate, the sharpness incentive could reward the opposite of what it is designed to prevent.

### 3.5 The Correlation Discount

Five technical-analysis producers emitting correlated signals would dominate synthesis through volume, not information content. The system discounts redundant signal by penalizing producers whose forecasts align with existing ensemble conviction. This novelty penalty is deployed in shadow mode, measuring its effect before it influences weights.

### 3.6 The Compound Loop

Karma feeds back into synthesis.

When the brain combines signals from multiple producers, it weights each producer by karma. High-karma producers contribute more to the aggregate conviction. Low-karma producers contribute less.

This creates compound learning:

```
Signal → Trade → Outcome → Attribution → Karma Update → Weight Adjustment → Better Signal Selection
```

The system that accurately attributed yesterday's outcomes makes better-weighted decisions today. The improvement is not hypothetical—it is measured by the same Brier scoring that drives attribution.

---

## Three Evaluation Layers

Forecast quality, attribution quality, and portfolio performance are distinct but linked evaluation domains.

A producer can be well-calibrated probabilistically (good Brier score) while being economically useless after fees and slippage. b1e55ed treats these three layers separately:

1. **Forecast layer** — Did the forecast resolve correctly under the canonical event definition? Scored by Brier.
2. **Attribution layer** — Which producers contributed to synthesis and at what weight? Tracked by karma.
3. **Portfolio layer** — Did the resulting positions outperform all four benchmarks after fees, slippage, and risk constraints?

The system's primary proof metric is at the portfolio layer: do forecasts assigned higher confidence produce better realized economic outcomes than lower-confidence forecasts, net of fees, under identical execution assumptions?

---

## 4. Falsifiability

A trading system is falsifiable if it makes predictions that can be proven wrong.

Most systems fail this test. They predict "BTC will go up" without specifying when, by how much, or with what confidence. They claim edge without defining what would constitute evidence against it.

b1e55ed is falsifiable by construction:

- Every forecast has a horizon. When the horizon elapses, the forecast is either correct or incorrect.
- Every confidence claim is testable. A producer claiming 70% confidence should be right 70% of the time.
- Every producer's track record is verifiable. The event store contains the complete history.

### 4.1 The Four Benchmarks

A system that beats random chance may still fail to add value. The relevant question is not "does this system beat zero?" but "does this system beat alternatives?"

b1e55ed runs four benchmarks continuously:

1. **Flat/no-trade**: Zero exposure. Earns the risk-free rate. Pays no fees. Any system that underperforms flat is destroying value through overtrading.

2. **Naive momentum**: Long above 20-period moving average, short below. A minimal systematic strategy.

3. **Equal-weight ensemble**: Average all producer signals with uniform weights. If the brain cannot beat equal weights, its weighting mechanism is not adding value.

4. **Discretionary**: Human operator override when available.

The brain must beat all four benchmarks to claim edge. All benchmark comparisons run under identical assumptions: same market data source, same fee model, same slippage assumptions, same execution timestamps.

---

## 5. The Intelligence Layer

### 5.1 Shadow-First Philosophy

Every adaptive component in b1e55ed defaults to observation mode.

When a new interpreter layer is added—regime conditioning, LLM critique, confidence adjustment—it runs in shadow mode. It logs what it would have done. It does not modify the actual forecast.

An adaptive system that acts before it has learned is worse than a static system. Shadow mode ensures that every adaptive layer accumulates data on its own performance before it earns the right to affect decisions.

### 5.2 The 500-Outcome Gate

The meta-producer learns ensemble patterns: which combinations of producer signals have historically led to correct outcomes.

It does not emit actionable forecasts until 500 outcomes have been resolved.

The 500-outcome gate is an operational minimum chosen to reduce obvious overfitting risk before the meta-producer influences synthesis. At 500 outcomes across multiple producers, assets, and regimes, statistical regularities become distinguishable from noise for the effect sizes the system is designed to detect. The exact threshold is a conservative hyperparameter — too low risks activating on noise, too high delays genuine learning.

### 5.3 Activation Sequence

After the 500-outcome gate is passed, the meta-producer transitions from shadow mode to advisory mode. It emits forecasts but does not automatically affect synthesis weights.

Only after demonstrating positive contribution to the Brier score over a further observation period does it earn weight in the synthesis function.

---

## 6. Contributor Network

### 6.1 Producer Registration

Signal producers register with a node identity. Producer identities are cryptographically persistent, binding forecast history to a stable key over time.

Registration requires:

- A unique producer ID
- Declaration of domain (onchain, tradfi, technical, social, events, curator)
- Initial karma score of 1.0 (neutral)

Sybil resistance relies on a combination of reputation cold-start (new producers carry no karma weight), registration attestation via EAS, and the economic cost of building karma from zero.

### 6.2 Karma as Verifiable Attribution

Karma scores are public within the system. Any observer can verify:

- A producer's historical forecasts
- The outcomes of those forecasts
- The resulting karma trajectory

A producer cannot claim a track record it does not have. The event store is the single source of truth.

### 6.3 The Oracle as Platform

The oracle serves producer track records from the same append-only, hash-linked event log that drives the engine. In the current beta architecture, verification relies on hash chain integrity and reproducible replay within the operator's trust boundary. The system is designed for cryptographic auditability — hash-linked today, external chain anchoring on roadmap.

**Who the customer is.** Any trader who wants to access machine-verified producer track records without running the full b1e55ed stack.

**Why this is a platform.** The oracle decouples the accountability mechanism from the execution layer. Third parties can verify a producer's track record without trusting the operator, without running b1e55ed, without access to the underlying event store.

---

## 7. Properties

The system guarantees:

- **Immutability**: Forecasts are written to hash-linked event store; modification is detectable
- **Attribution**: Every trade is linked to contributing signals
- **Calibration feedback**: Brier scores are computed for every producer
- **Weight adjustment**: Karma affects synthesis weights
- **Benchmark comparison**: Four baselines run continuously
- **Kill switches**: Five conditions halt trading automatically

The system does not guarantee:

- **Profitability**: Edge is demonstrated, not assumed
- **Regime robustness**: Performance in one market regime may not transfer to another
- **Adversarial resistance**: Sophisticated gaming may find exploits not yet anticipated

---

## 8. Current Status

b1e55ed is in beta.

Version: 1.0.0-beta.8

### Implementation Status

| Component | Status |
|-----------|--------|
| Forecast emission, Brier scoring, outcome resolution | ✅ Implemented — beta.8 |
| Karma EMA attribution | ✅ Implemented — beta.8 |
| LLM critic, regime matrix, prosecutor | ✅ Deployed — shadow mode only |
| Cross-producer novelty penalty (P4.3) | ✅ Deployed — shadow mode only |
| Meta-producer | ✅ Deployed — activates at 500 outcomes |
| Sharpness multiplier on karma | ⚗️ Specified, not yet deployed |
| Regime-conditional karma decay (HMM) | ⚗️ Research design |
| EAS registration attestation | ⚗️ Roadmap |
| External chain anchoring for oracle | ⚗️ Roadmap |

The system is not inert before external contributors join. Thirteen internal producers — spanning on-chain flows, technical analysis, TradFi basis, sentiment, and social signals — run from first deployment. External contributors join a system that already has a track record, not an empty one.

The following components are operational:

- Signal attribution layer emitting `SIGNAL_ACCEPTED_V1` events
- Karma wiring updating `producer_karma` on position close
- Four benchmarks running continuously
- Five kill switch conditions enforced
- Cockpit dashboard for daily review

The 30-day proof question: do high-confidence signals (>0.65) outperform low-confidence signals (<0.45) after fees?

Current data accumulation began February 2026. The 500-outcome gate for meta-producer activation has not yet been reached. All adaptive layers remain in shadow mode.

---

## Conclusion

b1e55ed does not claim to be profitable. It claims to be falsifiable.

Every forecast is testable. Every producer is accountable. Every outcome feeds back into weights. The system either demonstrates edge against benchmarks or it does not.

---

## References

- Gneiting, T. & Raftery, A.E. (2007). Strictly Proper Scoring Rules, Prediction, and Estimation. *Journal of the American Statistical Association*, 102(477), 359–378.
- Hamilton, J.D. (1989). A New Approach to the Economic Analysis of Nonstationary Time Series and the Business Cycle. *Econometrica*, 57(2), 357–384.
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley.

<!-- Nine pages changed the topology of trust. Seven thousand words attempt to change the topology of accountability. -->
