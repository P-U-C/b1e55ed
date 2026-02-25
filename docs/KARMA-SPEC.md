# KARMA-SPEC.md — Karma Scoring Specification

> Version: 1.0.0  
> Status: Canonical  
> Scope: Signal-producer karma scores used by the b1e55ed provenance oracle.

---

## Overview

Karma is a **running estimate of signal quality** for a registered producer.
It is not a trust score.  It does not predict future performance.  It is a
compressed historical summary of past outcomes — nothing more.

The oracle exposes karma-derived data so downstream agents can make their own
decisions.  The system does not tell agents what to do with this information.

---

## 1. Inputs — What Fields Move Karma

### 1.1 Signal Direction Correctness

The primary input.  A signal is "correct" if the predicted direction
(long/short/neutral) matches the actual price outcome at the resolution
horizon.

| Outcome             | `outcome_score` |
|---------------------|-----------------|
| Correct direction   | `1.0`           |
| Incorrect direction | `0.0`           |
| Neutral / unknown   | `0.5`           |

### 1.2 Time-to-Outcome

Faster correct signals score higher.  A correct signal that resolves in 1 hour
contributes more per unit of information than the same signal resolved in 30
days, because the producer held conviction through a shorter uncertainty window.

**Implementation:** The raw `outcome_score` is scaled by a time-decay factor
before being used in the update rule:

```
time_weight = exp(-lambda * hours_to_outcome)
```

where `lambda = 0.005` by default (roughly 50% weight at 139 hours ≈ 6 days).
This factor is applied before the karma update, not after.

### 1.3 Operator Weight

Signals from operators with more verified on-chain capital carry a higher
weight multiplier.  The multiplier is bounded `[0.5, 2.0]` to prevent any
single operator from dominating scores.

```
operator_weight = clamp(log10(verified_capital_usd + 1) / 6.0, 0.5, 2.0)
```

This is currently best-effort; if no capital verification is available,
`operator_weight = 1.0`.

### 1.4 Signal Frequency Penalty

Noise generators produce many signals quickly.  The karma update is divided by
a penalty factor if a producer emits signals above a threshold rate:

```
if signals_per_day > FREQUENCY_THRESHOLD:
    outcome_score *= (FREQUENCY_THRESHOLD / signals_per_day)
```

Default `FREQUENCY_THRESHOLD = 10` signals/day.  This penalises producers who
spam signals to game sample-size heuristics.

---

## 2. Update Rule — Exact Formula

```
karma_new = karma_old + learning_rate * (outcome_score - karma_old)
```

Where:
- `karma_old` ∈ `[0.0, 1.0]`  — current karma estimate
- `outcome_score` ∈ `{1.0, 0.5, 0.0}`  — win / neutral / loss
- `learning_rate = 0.1`  — configurable, default `0.1`

**Properties:**
- Karma is bounded `[0.0, 1.0]` by construction (exponential moving average).
- Early signals matter more than late signals due to compounding.
- A producer starting at `karma = 0.5` requires roughly 7 consecutive wins
  to cross `0.8`, and 7 consecutive losses to fall below `0.2`.
- `learning_rate` is configurable per-deployment.  Lower values make karma
  more stable but slower to adapt.  Higher values are more reactive but noisy.

**Initialisation:** All new producers start at `karma_initial = 0.5`
(maximum uncertainty prior).

---

## 3. Calibration — What Scores Mean Empirically

These thresholds are calibrated against the seed dataset (see `SEED_MANIFEST.md`).
They are not guarantees.

| Karma Range | Interpretation |
|-------------|----------------|
| `> 0.8`     | Strong positive attribution across multiple market regimes |
| `0.6–0.8`   | Positive attribution; limited data or single-regime track record |
| `0.4–0.6`   | Neutral — insufficient signal or genuinely mixed outcomes |
| `0.2–0.4`   | Negative attribution — below-chance performance over sample |
| `< 0.2`     | Persistent underperformance — consistent noise generation |

---

## 4. 30-Second Explainability Test

**Why is Producer A at 0.83 while Producer B is at 0.41?**

**Producer A — `synthetic_momentum_v1`**

| Signal # | Direction | Outcome | Score | Karma After |
|----------|-----------|---------|-------|-------------|
| 1  | long  | win  | 1.0 | 0.50 + 0.1×(1.0−0.50) = **0.55** |
| 2  | long  | win  | 1.0 | 0.55 + 0.1×(1.0−0.55) = **0.60** |
| 3  | short | win  | 1.0 | 0.60 + 0.1×(1.0−0.60) = **0.64** |
| 4  | long  | loss | 0.0 | 0.64 + 0.1×(0.0−0.64) = **0.58** |
| …  | …     | …    | …   | … (mostly wins) → **0.83** |

A had 18 wins and 4 losses over 90 days, across two distinct regimes (bull
and flat).  Each win was fast (median 4h resolution).  The losses were
recovered quickly.

**Producer B — `lagging_indicator_v1`**

| Signal # | Direction | Outcome | Score | Karma After |
|----------|-----------|---------|-------|-------------|
| 1  | long  | loss | 0.0 | 0.50 + 0.1×(0.0−0.50) = **0.45** |
| 2  | long  | loss | 0.0 | 0.45 + 0.1×(0.0−0.45) = **0.41** |
| 3  | long  | win  | 1.0 | 0.41 + 0.1×(1.0−0.41) = **0.47** |
| 4  | long  | loss | 0.0 | 0.47 + 0.1×(0.0−0.47) = **0.42** |
| …  | …     | …    | …   | … (alternating) → **0.41** |

B uses a 200-period SMA on 1h bars — a well-known lagging indicator.  It
wins roughly as often as it loses.  Its karma asymptotes near 0.41 because
the slight net-negative bias compounds over many signals.

**Conclusion:** 0.83 vs 0.41 reflects 90 days of compounded outcomes.
Neither score tells you what will happen next.

---

## 5. Failure Modes — What Karma Does NOT Claim

These are hard constraints on what karma is capable of expressing.
Downstream systems must account for these when consuming provenance data.

### 5.1 Not Predictive of Future Performance

Karma is backward-looking by design.  A producer with karma 0.83 may
immediately enter a drawdown.  Past attribution is not a guarantee of
future signal quality.

### 5.2 Not Regime-Aware by Default

The base karma update does not condition on market regime.  A producer that
performs well only in bull markets will show elevated karma during bull runs
and crash in flat/bear regimes without the score having warned you.

Regime-conditioned karma scores are a separate (optional) feature tracked
under a different key and are not part of this spec.

### 5.3 Not Sybil-Resistant Until Forge Cost Is Implemented

Currently, a bad actor can register multiple producers (at low cost) and
run them in parallel, cherry-picking the one that happens to win.  The
selected producer will appear to have high karma.

Sybil resistance requires non-trivial registration cost (Forge-based proof
of work or on-chain stake).  Until that is implemented, treat any producer
with fewer than 30 signals or a very short track record with scepticism.

### 5.4 Cannot Detect Coordinated Gaming Across Multiple Operators

If multiple operators submit correlated signals from different registered
identities, the karma system will not detect this unless the signals are
traced back to the same underlying model.  Attribution clustering is a
future capability.

### 5.5 Sparse Data → Unstable Scores

Fewer than 30 resolved signals is insufficient for reliable karma
estimation.  The exponential moving average has not converged; a single
lucky streak can dominate the score.

**Rule of thumb:** treat scores with `total_signals < 30` as "insufficient
data" regardless of the numerical value.

---

## 6. Configuration Reference

| Parameter           | Default | Description                           |
|---------------------|---------|---------------------------------------|
| `learning_rate`     | `0.1`   | EMA learning rate                     |
| `karma_initial`     | `0.5`   | Starting karma for new producers      |
| `frequency_threshold` | `10`  | Max signals/day before penalty kicks in |
| `time_decay_lambda` | `0.005` | Time-to-outcome decay rate (per hour) |
| `min_signals`       | `30`    | Minimum for stable estimate warning   |

---

## 7. Governance

Karma parameters are **not automatically updated** by the learning loop.
Changes require operator approval (`approved = 1` in `learning_weights`)
and are logged in the audit trail.

The formula itself is part of the canonical spec.  Any change to the formula
requires a version bump in this document and a migration of all stored karma
scores (or a cold-start).

---

*The code remembers. The hex is blessed: 0xb1e55ed.*
