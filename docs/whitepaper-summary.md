# b1e55ed: A Falsifiable Profit Engine

**March 2026**

---

## Abstract

Trading systems claim edge but cannot prove it. The problem is structural: without closed attribution between signals and outcomes, skill cannot be separated from luck. b1e55ed solves this by making every forecast a falsifiable, immutable probability statement. Each forecast carries direction, confidence, horizon, and producer attribution. Outcomes are resolved against realized prices. Resolution produces a Brier score for every producer, every cycle. Those scores feed back into calibration and domain weights. The loop closes. The system compounds.

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

The attribution problem compounds. After a hundred trades, you know aggregate P&L. You do not know which signal sources earned that P&L. After a thousand trades, the system has learned nothing about itself.

b1e55ed makes attribution structural.

---

## 3. The b1e55ed Mechanism

### 3.1 Forecasts as Immutable Probability Statements

Every signal source in b1e55ed emits forecasts with a fixed schema:

- **Direction**: long, short, or flat
- **Confidence**: a probability between 0 and 1
- **Horizon**: the time window over which the forecast applies
- **Producer ID**: the source of the forecast

Forecasts are persisted to an append-only event store. They cannot be modified after emission. This immutability is not a policy preference—it is a structural property enforced by the storage layer.

### 3.2 Resolution Against Realized Prices

When a forecast's horizon elapses, an outcome resolver compares the predicted direction against actual price movement.

The resolver computes:

- **Direction correctness**: did price move in the predicted direction?
- **Brier score**: (confidence − outcome)², where outcome is 1 if correct, 0 if incorrect

The Brier score is a proper scoring rule (Gneiting & Raftery, 2007). It penalizes overconfidence and underconfidence symmetrically. A forecaster who says "70% confident" should be correct 70% of the time across many forecasts. If they are correct 90% of the time, they were underconfident. If correct 50% of the time, they were overconfident. The Brier score captures both calibration and resolution.

### 3.3 Karma as Producer Weight

Each signal producer accumulates a karma score based on resolved outcomes.

When a position closes:

1. The system retrieves all signals that contributed to the trade
2. For each contributing producer, it computes an outcome value: +1 for correct direction, −1 for incorrect
3. Karma updates via exponential moving average: `karma_new = karma_old × 0.95 + outcome × 0.05`

This update rule (α = 0.05) gives recent outcomes weight while retaining memory of historical performance. A producer who has been consistently correct will have high karma. A producer who has been consistently wrong will have low karma. A producer who has been random will drift toward neutral.

**Regime non-stationarity.** The EMA with α = 0.05 means approximately 95% of karma weight reflects the last ~100 outcomes. This creates a vulnerability: a trend-following producer accumulates high karma during trending periods, then receives maximum weight exactly when regime shifts and their edge disappears. The system addresses this through regime-conditional decay (Hamilton, 1989): when a regime change is detected via hidden Markov model transition probabilities, the EMA decay rate increases temporarily (α → 0.15), accelerating karma recalibration. Karma scores are not assumed portable across detected regime boundaries.

### 3.4 Adversarial Dynamics and the Sharpness Incentive

**The Goodhart problem.** Once karma determines weight, rational producers have an incentive to game the scoring mechanism. The naive attack: emit forecasts clustered around 0.50–0.55 confidence. Such forecasts achieve near-optimal Brier scores regardless of outcome—technically well-calibrated but informationally useless. The producer earns karma while contributing nothing.

This is Goodhart's Law applied to forecast systems: when a measure becomes a target, it ceases to be a good measure.

**The Brier decomposition.** The Brier score decomposes into calibration (how well confidence matches realized frequency) and resolution (how much forecasts deviate from the base rate). A producer emitting 0.50 confidence achieves perfect calibration but zero resolution. The system must reward resolution, not merely calibration.

**The sharpness incentive.** b1e55ed addresses this through resolution-weighted karma: producers who make bold forecasts (confidence far from 0.50) and prove correct earn disproportionately higher karma than timid forecasters. The karma update includes a resolution multiplier: `resolution_factor = |confidence - 0.5| × 2`. A correct call at 0.90 confidence contributes more to karma than a correct call at 0.55 confidence, proportional to the information content of the forecast.

This creates the intended incentive gradient: timid forecasts cannot accumulate high karma, regardless of calibration.

### 3.5 The Correlation Discount

Five technical-analysis producers emitting correlated signals would dominate synthesis through volume, not information content. The system must discount redundant signal.

The NoveltyInterpreter (P4.3) addresses this directly: it penalizes producers whose forecasts agree with existing brain conviction. When a producer emits a signal that matches the current synthesis direction, its contribution is discounted by the degree of agreement. This is the correlation discount—agreement with consensus earns less karma than novel, correct disagreement.

The mechanism: for each incoming signal, compute `novelty = 1 - |correlation(signal, current_conviction)|`. Karma contribution scales by novelty factor. Producers are incentivized to find information the system does not already have.

### 3.6 Position Sizing and Attribution Weights

Signal quality without position sizing rules is half a system.

Direction and confidence map to position size via fractional Kelly: `size = (edge × kelly_fraction) / odds`. A 0.90 confidence correct call and a 0.55 confidence correct call contribute different dollar P&L—the attribution weights must reflect this.

When computing producer karma from position outcomes, the attribution weight is proportional to the position size that signal confidence implied. A producer whose high-confidence calls lead to larger positions earns more karma from correct calls (and loses more from incorrect ones). This aligns producer incentives with capital efficiency.

### 3.7 The Compound Loop

Karma feeds back into synthesis.

When the brain combines signals from multiple producers, it weights each producer by karma. High-karma producers contribute more to the aggregate conviction. Low-karma producers contribute less.

This creates compound learning:

```
Signal → Trade → Outcome → Attribution → Karma Update → Weight Adjustment → Better Signal Selection
```

The system that accurately attributed yesterday's outcomes makes better-weighted decisions today. The improvement is not hypothetical—it is measured by the same Brier scoring that drives attribution.

---

## 4. Falsifiability

A trading system is falsifiable if it makes predictions that can be proven wrong.

Most systems fail this test. They predict "BTC will go up" without specifying when, by how much, or with what confidence. They report aggregate returns without specifying which calls contributed. They claim edge without defining what would constitute evidence against it.

b1e55ed is falsifiable by construction:

- Every forecast has a horizon. When the horizon elapses, the forecast is either correct or incorrect.
- Every confidence claim is testable. A producer claiming 70% confidence should be right 70% of the time.
- Every producer's track record is verifiable. The event store contains the complete history.

### 4.1 The Four Benchmarks

A system that beats random chance may still fail to add value. The relevant question is not "does this system beat zero?" but "does this system beat alternatives?"

b1e55ed runs four benchmarks continuously:

1. **Flat/no-trade**: Zero exposure. Earns the risk-free rate. Pays no fees. This is the most important benchmark. Any system that underperforms flat is destroying value through overtrading.

2. **Naive momentum**: Long above 20-period moving average, short below. A minimal systematic strategy. If the brain cannot beat this, its additional complexity is not justified.

3. **Equal-weight ensemble**: Average all producer signals with uniform weights. If the brain cannot beat equal weights, its weighting mechanism is not adding value.

4. **Discretionary**: Human operator override when available. If the brain cannot beat informed human judgment, it should defer to the human.

The brain must beat all four benchmarks to claim edge. "Edge" means: risk-adjusted returns net of fees exceed the best alternative.

---

## 5. The Intelligence Layer

### 5.1 Shadow-First Philosophy

Every adaptive component in b1e55ed defaults to observation mode.

When a new interpreter layer is added—regime conditioning, LLM critique, confidence adjustment—it runs in shadow mode. It logs what it would have done. It does not modify the actual forecast.

This is not caution. It is discipline.

An adaptive system that acts before it has learned is worse than a static system. It compounds errors instead of correcting them. Shadow mode ensures that every adaptive layer accumulates data on its own performance before it earns the right to affect decisions.

### 5.2 The 500-Outcome Gate

The meta-producer learns ensemble patterns: which combinations of producer signals have historically led to correct outcomes.

It does not emit actionable forecasts until 500 outcomes have been resolved.

**Power analysis framing.** To detect a 5% improvement in Brier score over baseline with 80% statistical power requires a minimum sample size that depends on outcome variance. For typical forecast calibration variance (σ² ≈ 0.04), standard power calculations yield n ≈ 400–600 outcomes. The 500-outcome gate represents a conservative threshold within this range, calibrated empirically from simulation of the producer population.

This threshold would change under different conditions: higher effect size (easier to detect) would lower n; lower baseline variance would raise it; different power requirements (90% instead of 80%) would increase it. The specific value is not a universal constant—it is a parameter that reflects the system's tolerance for false positive pattern detection.

Below this threshold, apparent patterns are more likely noise than signal. The gate enforces epistemic honesty about what the data can support.

### 5.3 Activation Sequence

After the 500-outcome gate is passed, the meta-producer transitions from shadow mode to advisory mode. It emits forecasts but does not automatically affect synthesis weights.

Only after demonstrating positive contribution to the Brier score over a further observation period does it earn weight in the synthesis function.

This staged activation—shadow, advisory, weighted—ensures that every component proves its value before it affects capital allocation.

---

## 6. Contributor Network

### 6.1 Producer Registration

Signal producers register with a node identity. This identity is cryptographically stable—the same producer cannot claim to be multiple producers.

Registration requires:

- A unique producer ID
- Declaration of domain (onchain, tradfi, technical, social, events, curator)
- Initial karma score of 1.0 (neutral)

### 6.2 Karma as Verifiable Attribution

Karma scores are public within the system. Any observer can verify:

- A producer's historical forecasts
- The outcomes of those forecasts
- The resulting karma trajectory

This verifiability is what makes attribution meaningful. A producer cannot claim a track record it does not have. The event store is the single source of truth.

### 6.3 The Oracle as Platform

The oracle is a read-only projection of the event store. It answers one question: does a signal producer have verifiable history?

**Who the customer is.** Any trader who wants to access machine-verified producer track records without running the full b1e55ed stack. Hedge funds evaluating signal providers. Retail traders assessing influencer calls. Platforms building leaderboards. Anyone who needs to distinguish luck from skill in forecast accuracy claims.

**How value flows.** Operators earn attribution when their producer signals contribute to profitable outcomes. The oracle makes these track records publicly verifiable—a producer cannot inflate their history, and an operator cannot hide poor performance. This creates a market for verified signal quality where reputation is earned, not claimed.

**Why this is a platform, not infrastructure.** The oracle decouples the accountability mechanism from the execution layer. Third parties can verify a producer's track record without trusting the operator, without running b1e55ed, without access to the underlying event store. The verification is cryptographic, not trust-based.

This is the commercially differentiated piece: verifiable signal track records as a service. The trading system is one use case. The oracle enables an ecosystem of applications that depend on knowing whether a forecaster has genuine skill.

---

## 7. Properties

The system guarantees:

- **Immutability**: Forecasts cannot be modified after emission
- **Attribution**: Every trade is linked to contributing signals
- **Calibration feedback**: Brier scores are computed for every producer
- **Resolution incentive**: Bold correct forecasts earn more than timid correct forecasts
- **Correlation discount**: Redundant signals are penalized via NoveltyInterpreter
- **Weight adjustment**: Karma affects synthesis weights
- **Regime conditioning**: Karma decay accelerates during detected regime changes
- **Benchmark comparison**: Four baselines run continuously
- **Kill switches**: Five conditions halt trading automatically (consecutive losses, single large loss, total risk exposure, data degradation, fill divergence)

The system does not guarantee:

- **Profitability**: Edge is demonstrated, not assumed
- **Regime robustness**: Performance in one market regime may not transfer to another
- **Producer quality**: The system learns from producers; it does not select which producers to trust initially
- **Adversarial resistance**: Sophisticated gaming may find exploits not yet anticipated
- **Latency**: The system is designed for swing trading horizons, not high-frequency

---

## 8. Current Status

b1e55ed is in beta.

Version: 1.0.0-beta.8

The flywheel sprint (S0–S7) closed the attribution loop. The following components are operational:

- Signal attribution layer emitting `SIGNAL_ACCEPTED_V1` events
- Karma wiring updating `producer_karma` on position close
- Four benchmarks running continuously
- Five kill switch conditions enforced
- Cockpit dashboard for daily review
- Stratification tracker for 30-day proof metric

The 30-day proof question: do high-confidence signals (>0.65) outperform low-confidence signals (<0.45) after fees?

If yes, the weighting mechanism works. If no, the system has not demonstrated edge.

Current data accumulation began February 2026. The 500-outcome gate for meta-producer activation has not yet been reached. All adaptive layers remain in shadow mode.

Phase 0 completion criteria:

1. At least 50 paper trades completed
2. Stratification shows high-confidence outperforming low-confidence
3. All four benchmarks running for 14+ days
4. Cockpit reviewed daily for one week without issues

At that point: decision on live capital deployment.

---

## Conclusion

b1e55ed does not claim to be profitable. It claims to be falsifiable.

Every forecast is testable. Every producer is accountable. Every outcome feeds back into weights. The system either demonstrates edge against benchmarks or it does not.

This is the only honest claim a trading system can make.

---

## References

Gneiting, T., & Raftery, A. E. (2007). Strictly proper scoring rules, prediction, and estimation. *Journal of the American Statistical Association*, 102(477), 359–378.

Hamilton, J. D. (1989). A new approach to the economic analysis of nonstationary time series and the business cycle. *Econometrica*, 57(2), 357–384.

---

*"The system that learns from its own outcomes will outperform systems that don't."*
