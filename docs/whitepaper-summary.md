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

The Brier score is a proper scoring rule. It penalizes overconfidence and underconfidence symmetrically. A forecaster who says "70% confident" should be correct 70% of the time across many forecasts. If they are correct 90% of the time, they were underconfident. If correct 50% of the time, they were overconfident. The Brier score captures both calibration and resolution.

### 3.3 Karma as Producer Weight

Each signal producer accumulates a karma score based on resolved outcomes.

When a position closes:

1. The system retrieves all signals that contributed to the trade
2. For each contributing producer, it computes an outcome value: +1 for correct direction, −1 for incorrect
3. Karma updates via exponential moving average: `karma_new = karma_old × 0.95 + outcome × 0.05`

This update rule (α = 0.05) gives recent outcomes weight while retaining memory of historical performance. A producer who has been consistently correct will have high karma. A producer who has been consistently wrong will have low karma. A producer who has been random will drift toward neutral.

### 3.4 The Compound Loop

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

Below 500 outcomes, the sample size is insufficient to distinguish signal from noise. A pattern that appears predictive at n=50 may be random variation. At n=500, statistical regularities become identifiable.

This gate is not configurable. It is a structural minimum.

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

### 6.3 The Oracle

The oracle is a read-only projection of the event store. It answers one question: does a signal producer have verifiable history?

External systems can query the oracle without authentication. They receive provenance data—historical forecasts, outcomes, karma scores—sufficient to verify any claimed track record.

The oracle does not interpret. It does not recommend. It provides facts that enable independent verification.

---

## 7. Properties

The system guarantees:

- **Immutability**: Forecasts cannot be modified after emission
- **Attribution**: Every trade is linked to contributing signals
- **Calibration feedback**: Brier scores are computed for every producer
- **Weight adjustment**: Karma affects synthesis weights
- **Benchmark comparison**: Four baselines run continuously
- **Kill switches**: Five conditions halt trading automatically (consecutive losses, single large loss, total risk exposure, data degradation, fill divergence)

The system does not guarantee:

- **Profitability**: Edge is demonstrated, not assumed
- **Regime robustness**: Performance in one market regime may not transfer to another
- **Producer quality**: The system learns from producers; it does not select which producers to trust initially
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

*"The system that learns from its own outcomes will outperform systems that don't."*
