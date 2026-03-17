# KARMA-SPEC.md — Karma Scoring Specification

> Version: 1.1.0  
> Status: Canonical  
> Scope: Contributor karma scores used by the b1e55ed provenance oracle.

---

## Overview

Karma is a **composite reputation score** for a registered contributor.
It is not a trust score.  It does not predict future performance.  It is a
compressed historical summary of past outcomes — nothing more.

The oracle exposes karma-derived data so downstream agents can make their own
decisions.  The system does not tell agents what to do with this information.

---

## 1. Score Formula — 5-Factor Composite

The karma score is a weighted composite of five independent factors, scaled
to the range `[0, 100]`:

```
score = 100 × clamp(
    0.35 × hit_rate_norm
  + 0.20 × calibration_norm
  + 0.20 × volume_norm
  + 0.15 × consistency_norm
  + 0.10 × recency
, 0, 1)
```

| Component         | Weight | Source                               |
|-------------------|--------|--------------------------------------|
| `hit_rate_norm`   | 35%    | Profitable signals / resolved signals |
| `calibration_norm`| 20%    | Brier score quality (lower = better) |
| `volume_norm`     | 20%    | Accepted signals, log-scaled          |
| `consistency_norm`| 15%    | Sqrt-scaled streak of active days     |
| `recency`         | 10%    | Days since last accepted signal       |

Hit rate receives the highest weight because it is the hardest to game: it
requires accepted signals with confirmed profitable outcomes.

**Initialisation:** New contributors start at `score = 0.0`.  A score can
only increase once resolved signals accumulate.

---

## 2. Component Definitions

### 2.1 Hit Rate (35%)

```
hit_rate = signals_profitable / signals_resolved
```

Where:
- `signals_profitable` — accepted signals where `profitable = 1`
- `signals_resolved`   — accepted signals where `profitable IS NOT NULL`
  (i.e., the outcome has been recorded, regardless of win/loss)

**Gate:** If `signals_resolved < 5`, `hit_rate = 0.0` (insufficient data; contributor is not penalised but also not rewarded).

**Normalisation:** `hit_rate_norm = clamp(hit_rate, 0, 1)`.

**Penalty:** If `signals_resolved ≥ 5` and `hit_rate < 0.20`, the component goes slightly negative:

```
hit_rate_norm = -0.1 × (0.20 − hit_rate) / 0.20
```

This scales from `0` at `hit_rate = 0.20` to `−0.10` at `hit_rate = 0.0`,
creating a mild downward pressure for persistently wrong signals.

### 2.2 Calibration — Brier Score (20%)

Calibration measures how well a contributor's stated conviction matches
actual outcomes, using the **Brier score**:

```
brier = mean((confidence − outcome)²)
```

Where:
- `confidence = clamp(signal_score / 10, 0, 1)` — normalised conviction
- `outcome = 1` if `profitable = 1`, else `0`

Lower Brier scores are better.  The random-guess baseline is `0.25`.

**Normalisation:**

```
calibration_norm = clamp(1 − brier / 0.25, 0, 1)
```

A perfect Brier score of `0.0` → `calibration_norm = 1.0`.  
A random baseline of `0.25` → `calibration_norm = 0.0`.  
Worse than random (`brier > 0.25`) is clamped to `0.0`.

**Gate:** Requires at least 5 resolved signals; returns neutral `0.25` otherwise.

### 2.3 Volume (20%)

Volume counts **accepted** signals only, not submitted.  This closes the
most obvious gaming vector (submitting garbage signals to inflate counts).

```
volume_norm = clamp(log₁₊(accepted) / log₁₊(100), 0, 1)
```

Diminishing returns via log scaling.  A contributor needs roughly 100
accepted signals to saturate this component.

### 2.4 Consistency — Streak (15%)

Consistency rewards sustained activity, not burst submissions.

```
streak = consecutive calendar days with ≥ 1 accepted signal
consistency_norm = clamp(√streak / √30, 0, 1)
```

Sqrt scaling gives diminishing returns (going from day 1→2 is worth more
than going from day 29→30).  A 30-day streak saturates this component.

**Note:** Only days with at least one **accepted** signal count toward the
streak.  Submitting signals that are not accepted does not advance the streak.

### 2.5 Recency (10%)

Recency rewards contributors who are actively submitting.

- Within 7 days of last accepted signal: `recency = 1.0`
- 7–37 days: linear decay from `1.0` to `0.0`
- Beyond 37 days: `recency = 0.0`

```
if days_since ≤ 7:
    recency = 1.0
else:
    recency = clamp(1 − (days_since − 7) / 30, 0, 1)
```

---

## 3. Anti-Gaming Measures

### 3.1 Acceptance Rate Gate

If a contributor has submitted 10 or more signals and fewer than 10% have
been accepted, the system treats them as a noise generator and returns a
score of exactly `0.0` (all components zeroed).

```
if submitted ≥ 10 and accepted / submitted < 0.10:
    score = 0.0
```

### 3.2 Volume Counts Accepted Signals Only

The volume component (`2.3`) uses `signals_accepted`, not `signals_submitted`.
Spamming low-quality signals does not increase volume score.

### 3.3 Streak Counts Accepted Days Only

The consistency component (`2.4`) only increments the streak for days with
accepted signals.  Drip-farming (one signal per day, all rejected) has zero
effect on the streak.

### 3.4 Hit Rate Requires Resolved Outcomes

`hit_rate` is computed from signals with confirmed outcomes (`profitable IS
NOT NULL`), not from all accepted signals.  A contributor cannot inflate
their hit rate by avoiding resolution — unresolved signals contribute `0.0`
to the hit rate component.

### 3.5 Brier Score Calibration Penalty

If a contributor states high conviction on consistently wrong signals (i.e.,
`confidence` is high but `outcome` is `0`), the Brier score will exceed the
random baseline (`0.25`), driving `calibration_norm` toward `0.0`.

---

## 4. Score Interpretation

These thresholds are illustrative, not guarantees.

| Score Range | Interpretation |
|-------------|----------------|
| `> 75`      | Strong positive attribution — high hit rate, good calibration, sustained activity |
| `50–75`     | Positive attribution — solid outcomes but limited data or recency gap |
| `25–50`     | Neutral — insufficient resolved outcomes or mixed results |
| `< 25`      | Below baseline — low acceptance rate, wrong direction, or inactive |
| `= 0.0`     | New contributor or acceptance rate gate triggered |

---

## 5. 30-Second Explainability Test

**Why is Contributor A at 81 while Contributor B is at 23?**

**Contributor A — `synthetic_momentum_v1`**

| Metric                | Value     |
|-----------------------|-----------|
| `signals_submitted`   | 120       |
| `signals_accepted`    | 95 (79%)  |
| `signals_resolved`    | 80        |
| `signals_profitable`  | 62        |
| `hit_rate`            | 0.775     |
| `brier_score`         | 0.10      |
| `streak`              | 22 days   |
| `days_since_active`   | 2         |

Composite: `0.35×0.775 + 0.20×0.60 + 0.20×0.87 + 0.15×0.86 + 0.10×1.0 ≈ 0.81`  
→ **score ≈ 81**

**Contributor B — `lagging_indicator_v1`**

| Metric                | Value     |
|-----------------------|-----------|
| `signals_submitted`   | 40        |
| `signals_accepted`    | 18 (45%)  |
| `signals_resolved`    | 10        |
| `signals_profitable`  | 4         |
| `hit_rate`            | 0.40      |
| `brier_score`         | 0.22      |
| `streak`              | 3 days    |
| `days_since_active`   | 14        |

Composite: `0.35×0.40 + 0.20×0.12 + 0.20×0.43 + 0.15×0.32 + 0.10×0.23 ≈ 0.26`  
→ **score ≈ 26**

---

## 6. Failure Modes — What Karma Does NOT Claim

### 6.1 Not Predictive of Future Performance

Karma is backward-looking by design.  A contributor with score `81` may
immediately enter a drawdown.  Past attribution is not a guarantee of
future signal quality.

### 6.2 Not Regime-Aware by Default

The base karma score does not condition on market regime.  A contributor
that performs well only in bull markets will show elevated karma during bull
runs and may decline in flat/bear regimes without the score having warned you.

### 6.3 Not Sybil-Resistant Until Forge Cost Is Implemented

A bad actor can register multiple contributors and run them in parallel,
cherry-picking the one that happens to win.  The selected contributor will
appear to have a legitimate score.

Sybil resistance requires non-trivial registration cost (Forge-based proof
of work or on-chain stake).  Until that is implemented, treat any contributor
with fewer than 30 resolved signals with scepticism.

### 6.4 Sparse Data → Unstable Scores

Fewer than 30 resolved signals is insufficient for reliable karma estimation.
A single lucky streak can dominate the score.

**Rule of thumb:** treat scores with `signals_resolved < 30` as "insufficient
data" regardless of the numerical value.

---

## 7. Configuration Reference

| Parameter                  | Value  | Description                              |
|----------------------------|--------|------------------------------------------|
| `MIN_RESOLVED_FOR_HIT_RATE`| `5`    | Minimum resolved signals before hit rate counts |
| `MIN_ACCEPTANCE_RATE`      | `0.10` | Below this, contributor scores zero      |
| Hit rate penalty threshold  | `0.20` | Below 20% hit rate → mild negative score |
| Volume saturation           | `100`  | ~100 accepted signals saturates volume component |
| Streak saturation           | `30`   | 30-day streak saturates consistency component |
| Recency full credit         | `7`    | Last signal ≤ 7 days ago → full recency  |
| Recency decay window        | `30`   | Linear decay over 7–37 days              |

---

## 8. Governance

Karma parameters are **not automatically updated** by the learning loop.
Changes require operator approval and are logged in the audit trail.

The formula itself is part of the canonical spec.  Any change to the formula
requires a version bump in this document and a migration of all stored karma
scores (or a cold-start).

---

## Revision History

| Version | Date       | Change                                      |
|---------|------------|---------------------------------------------|
| 1.0.0   | 2025-01-01 | Initial spec — described EMA-based formula  |
| 1.1.0   | 2026-02-25 | **Rewritten to match implementation.** The EMA formula (learning_rate × karma update) was never implemented. The actual code (`engine/core/scoring.py`) uses a 5-factor weighted composite: `0.35*hit_rate + 0.20*calibration + 0.20*volume + 0.15*consistency + 0.10*recency`. Spec updated to reflect reality. |

---

*The code remembers. The hex is blessed: 0xb1e55ed.*
