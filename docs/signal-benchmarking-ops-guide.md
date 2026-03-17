---
title: "Signal Benchmarking Guide"
description: "Operational guide for oracle builders and signal performance evaluation."
---

# Signal Benchmarking Operations Guide for Oracle Builders

*From the b1e55ed project — a continuous crypto signal aggregation and paper trading system. Everything here is from operational experience, not theory.*

---

## Introduction

If you're building a signal aggregation system — whether for crypto, equities, or any asset class — you need to answer one question before anything else: **do your signals actually have edge?**

This sounds obvious. It isn't. We spent weeks building producers, wiring up synthesis, watching convictions flow through the system, and feeling productive. Then we added benchmarks and discovered most of our signal pipeline was producing noise indistinguishable from a coin flip.

This guide covers what we learned building b1e55ed: a system where multiple **producers** (TA, whale tracking, on-chain flows, social sentiment, TradFi basis, orderbook depth) emit typed signal events into a SQLite database. A **Brain orchestrator** synthesizes these signals every 15 minutes using weighted scoring, outputting a conviction per asset with direction, confidence, and magnitude. A paper-mode **OMS** executes trades based on convictions. And **benchmarks** evaluate whether any of this actually works.

The stack is deliberately simple: single Ubuntu VM, FastAPI backend, SQLite (`brain.db`), HTMX dashboard. No Kubernetes. No Kafka. The complexity is in getting the signal loop right, not in infrastructure.

---

## 1. Benchmark Design Taxonomy

You need four benchmarks running simultaneously. Each one falsifies a specific claim about your system. If you can't beat all four, you don't have edge — you have complexity.

### 1.1 Flat / No-Trade Benchmark

**What it is:** Hold cash. Return = 0%.

**What it falsifies:** The claim that your system generates positive returns at all.

This is the null hypothesis. It sounds trivial, but we ran b1e55ed for two weeks before adding proper benchmarks and discovered that after accounting for simulated slippage and fees, the system was net negative. Every trade felt like action. The PnL said otherwise.

**Implementation:** Literally a constant zero line on your performance chart. The benchmark that requires no code — and the one most builders skip.

**When your system fails this:** You have negative edge. Your signals are worse than doing nothing. Common causes: overtrading on low-conviction signals, fee drag from high-frequency position churn, or systematic bias in your synthesis (see failure mode #1 below).

### 1.2 Naive Momentum Benchmark

**What it is:** Every 24 hours, buy the asset(s) that went up the most in the prior 24 hours. Equal-weight. Rebalance daily.

**What it falsifies:** The claim that your signals contain information beyond what's already in price.

Momentum is the simplest possible "strategy" — it requires zero signal infrastructure, zero synthesis, zero intelligence. Just look at what went up and buy it. If your 18-producer, multi-domain synthesis engine can't beat "buy what went up yesterday," your producers are adding noise, not signal.

**Implementation:**

```python
def naive_momentum_benchmark(assets: list[str], lookback_hours: int = 24) -> dict:
    """Buy top performer from last lookback period, equal weight."""
    returns = {}
    for asset in assets:
        price_now = get_price(asset)
        price_then = get_price(asset, hours_ago=lookback_hours)
        returns[asset] = (price_now - price_then) / price_then
    
    winner = max(returns, key=returns.get)
    return {"asset": winner, "direction": "long", "weight": 1.0}
```

**When your system fails this:** Your signal processing is destroying information that raw price already contains. Simplify. Often the issue is latency — by the time your producers emit, synthesize, and trade, the momentum signal has already played out.

### 1.3 Equal-Weight Ensemble Benchmark

**What it is:** Average all active producer signals with equal weight. No confidence scaling, no karma weighting, no magnitude threshold.

**What it falsifies:** The claim that your weighting scheme (confidence, karma, domain prioritization) improves over naive averaging.

This is the benchmark most builders don't think to add, and it's the most humbling. We found that for the first month of operation, equal-weight averaging outperformed our confidence-weighted synthesis. Why? Because our confidence scores were miscalibrated (clustering near 0.5 — see failure mode #7), so the weighting was adding noise. The "dumb" average was more robust.

**Implementation:**

```python
def equal_weight_ensemble(signals: list[Signal]) -> float:
    """Simple average across all active producer scores."""
    active = [s for s in signals if s.source != "no_source_configured"]
    if not active:
        return 0.5  # neutral
    return sum(s.score for s in active) / len(active)
```

**When your system fails this:** Your weighting scheme is worse than no weighting. Either your confidence scores are miscalibrated, your karma/reputation system hasn't converged, or you have too few producers for weighting to matter statistically.

### 1.4 Full System (Discretionary Weighted)

**What it is:** Your actual system — weighted synthesis with confidence scaling, magnitude thresholds, conviction gating, the works.

**What you're trying to prove:** That all the complexity — the multi-domain synthesis, the confidence weighting, the magnitude gates, the kill switches — actually produces better risk-adjusted returns than the three simpler approaches above.

In our implementation, this is the `VectorSynthesis.synthesize()` output with:
- Domain weights (TA: 0.25, on-chain: 0.20, sentiment: 0.15, etc.)
- Confidence scaling per producer based on historical accuracy
- Magnitude threshold: skip trades where `magnitude < 5.0`
- Direction gating: never trade on `direction == "neutral"`
- Kill switch: halt all trading if drawdown exceeds threshold

**The honest truth:** As of this writing, our full system beats the flat benchmark and the naive momentum benchmark on risk-adjusted terms (Sortino), but only marginally beats the equal-weight ensemble. The weighting adds value primarily in drawdown reduction, not in raw returns. That's still worth it — but it's a humbler result than we expected.

---

## 2. Data Pipeline Failure Modes

These are real bugs we shipped, discovered in production, and fixed. Every one of them corrupted our benchmark results before we caught them. If you're building a similar system, you will hit variants of these.

### 2.1 Bearish Conviction Bias from Missing Domains

**The bug:** `VectorSynthesis.synthesize()` treated missing or inactive domains as implicit zeros. If 7 of 10 domains had no active producers, their weight still counted — as zero. This dragged every synthesis score below 0.5, creating a persistent bearish bias.

**How it manifested:** Every conviction came out slightly bearish regardless of what the active producers were saying. We thought the market was bearish. The market was fine. Our math was broken.

**The fix:** Renormalize weights only across domains that actually produced scores in that cycle. If only 3 of 10 domains fire, those 3 domains get their weights renormalized to sum to 1.0. Cycles where zero domains produce anything default to neutral (0.5), not zero.

```python
def synthesize(self, signals_by_domain: dict[str, list[Signal]]) -> float:
    active_weights = {}
    active_scores = {}
    
    for domain, signals in signals_by_domain.items():
        if signals:  # domain actually produced something
            active_weights[domain] = self.domain_weights[domain]
            active_scores[domain] = self._domain_score(signals)
    
    if not active_weights:
        return 0.5  # neutral, not zero
    
    # Renormalize
    total_weight = sum(active_weights.values())
    return sum(
        active_scores[d] * (active_weights[d] / total_weight)
        for d in active_weights
    )
```

**Lesson:** Never let absent data implicitly contribute a value. Absent is absent, not zero.

### 2.2 Silent OMS Injection Failure

**The bug:** `api/main.py` constructed the OMS with `OMS(config, db)`, but the constructor actually required `preflight` and `sizer` keyword arguments. The exception was caught by a broad `try/except` that logged "no OMS injected" at INFO level and continued. The system ran for days without executing any trades. The dashboard showed convictions flowing. No trades appeared. We assumed the convictions weren't meeting thresholds.

**The fix:** Construct OMS with full kwargs, matching the CLI code path:

```python
# Before (broken, silently caught)
oms = OMS(config, db)

# After (correct)
oms = OMS(config, db, preflight=preflight_check, sizer=position_sizer)
```

And critically: **never broad-catch constructor failures for critical components.** If the OMS fails to initialize, the system should crash, not silently continue without it.

**Lesson:** Silent failures in trading systems are worse than crashes. A crash tells you something's wrong. Silent degradation lets you believe you're running when you're not.

### 2.3 Neutral Convictions Triggering Trades

**The bug:** The orchestrator had this line:

```python
direction = conviction.direction if conviction.direction != "neutral" else "long"
```

Read that again. If the system had no directional conviction, it defaulted to **long**. Every ambiguous signal became a buy order. In a ranging market, this opened dozens of small long positions on assets the system had no opinion about.

**The fix:** Hard gate. If direction is neutral, skip the trade entirely:

```python
if conviction.direction == "neutral":
    logger.info(f"Skipping {symbol}: neutral conviction")
    continue
```

**Lesson:** Default values in trading logic are landmines. Every default should be "do nothing," not "do something." The safest trade is the one you don't take.

### 2.4 Inverted Stop/Target on Short Positions

**The bug:** The OMS computed stop-loss and take-profit levels using the same formula for both longs and shorts:

```python
stop = mid * (1 + stop_pct)    # e.g., 5% above entry
target = mid * (1 - target_pct)  # e.g., 10% below entry
```

For longs, this is correct: stop below entry, target above entry. For shorts, it's inverted: the stop should be *above* entry (you lose money when price goes up), and the target should be *below* entry (you profit when price goes down). With the original code, every short position had its stop *below* entry — meaning upward price moves (which lose money on shorts) would never trigger the stop.

**The fix:** Direction-aware math:

```python
if direction == "long":
    stop = mid * (1 - stop_pct)
    target = mid * (1 + target_pct)
elif direction == "short":
    stop = mid * (1 + stop_pct)
    target = mid * (1 - target_pct)
```

Plus a one-time DB migration to fix existing open short positions with inverted levels.

**Lesson:** Any position management code that doesn't branch on direction is almost certainly wrong. Write separate test cases for long and short from day one.

### 2.5 Event Type String Mismatch

**The bug:** The Brain orchestrator queried for mid-prices using:

```sql
SELECT * FROM events WHERE type = 'PRICE_V1'
```

But the price producer emitted events with type `signal.price_ws.v1`. The orchestrator never found mid-prices, so it couldn't compute entry levels for trade execution. Convictions were generated but never acted on because the OMS couldn't determine what price to enter at.

**The fix:** Query for both variants:

```sql
SELECT * FROM events WHERE type IN ('signal.price_ws.v1', 'PRICE_V1')
```

And longer-term: establish a canonical event type registry and validate producer output against it at emit time.

**Lesson:** String-typed event systems will bite you. Every producer and every consumer must agree on exact type strings. A registry or enum is better than convention.

### 2.6 Confidence Score Clustering

**The bug:** Most convictions showed confidence between 0.48 and 0.59 with "neutral" direction. We thought this meant the market was genuinely uncertain. The real cause: 7 of 18 producers were dead (status: `no_source_configured`), leaving only 1-2 domains actually driving synthesis. With so few inputs, the weighted average regressed to the mean. The system *couldn't* produce high-confidence signals because it didn't have enough signal diversity.

**The fix:** This isn't a code fix — it's an operational one:

1. Monitor producer health continuously. Dashboard shows per-producer last-emit timestamp.
2. Alert if fewer than N domains are active (we use N=3 as minimum).
3. Suspend auto-trading if domain coverage drops below threshold.
4. Fix or replace dead producers before trusting synthesis output.

**Lesson:** A synthesis engine is only as good as its inputs. Garbage in, neutral out. Monitor producer health as aggressively as you monitor PnL.

### 2.7 No Magnitude Threshold

**The bug:** Any directional signal triggered a trade, regardless of magnitude. A conviction with direction "long," confidence 0.62, and magnitude 1.2 (barely above noise) opened the same size position as one with magnitude 8.5 (strong signal). This led to a flood of low-conviction trades that individually didn't lose much but collectively dragged performance through fee accumulation and portfolio fragmentation.

**The fix:** Add a minimum magnitude threshold in config:

```yaml
auto_paper_trade_min_magnitude: 5.0
```

```python
if abs(conviction.magnitude) < config.auto_paper_trade_min_magnitude:
    logger.info(f"Skipping {symbol}: magnitude {conviction.magnitude} below threshold")
    continue
```

**Lesson:** Conviction gating needs multiple dimensions. Direction alone isn't enough. Confidence alone isn't enough. You need direction + confidence + magnitude all above threshold before opening a position.

---

## 3. Stratification Methodology

Running benchmarks tells you whether the system works. Stratification tells you *why* it works (or doesn't) and *where* the edge actually lives.

### 3.1 Confidence Binning

We bin every conviction into three cohorts:

| Cohort | Confidence Range | Expected Behavior |
|--------|-----------------|-------------------|
| LOW | < 0.45 | Should underperform or be skipped |
| MEDIUM | 0.45 – 0.65 | Marginal, may not survive fees |
| HIGH | > 0.65 | Should outperform meaningfully |

The core question: **does the HIGH cohort outperform MEDIUM, which outperforms LOW, after fees?** If yes, your confidence scores are calibrated — they actually predict outcome quality. If the cohorts perform similarly, your confidence score is decorative, not informative.

### 3.2 Sample Size Requirements

**Minimum 30 trades per cohort** before drawing any conclusions. This isn't arbitrary — it's the minimum for the Central Limit Theorem to give you roughly normal sampling distributions for mean returns.

In practice, 30 is a floor. We aim for 100+ per cohort before making system changes based on stratification data. At our trade frequency (2-5 trades/day in paper mode), this means ~3-6 weeks of data collection per evaluation cycle.

### 3.3 False Discovery Rate Correction

This is the single most important statistical concept for signal benchmarking, and almost nobody in crypto applies it.

**The problem:** If you test 20 strategies (or 20 producer combinations, or 20 parameter settings) at p < 0.05, you expect one false positive by chance alone. With enough backtests, everything looks significant.

**Our experience:** Without FDR correction, 14 of our 18 individual producer signals showed "statistically significant" edge in backtests. With Benjamini-Hochberg FDR correction at q = 0.05, only 3 survived. And of those 3, 2 were combined strategies (momentum + MA crossover), not single factors.

**Implementation:**

```python
from scipy.stats import false_discovery_control

def fdr_filter(p_values: list[float], q: float = 0.05) -> list[bool]:
    """Benjamini-Hochberg FDR correction. Returns mask of significant results."""
    adjusted = false_discovery_control(p_values, method='bh')
    return [p <= q for p in adjusted]
```

**What to actually measure per cohort:**

| Metric | Why |
|--------|-----|
| Win rate | Basic directional accuracy |
| Mean return per trade | Magnitude of edge |
| Sharpe ratio | Risk-adjusted return |
| Sortino ratio | Downside-risk-adjusted return (we prefer this) |
| Max drawdown | Worst-case pain |
| Profit factor | Gross wins / gross losses |
| Trade count | Sample size sanity check |

### 3.4 What We Actually Found

After 6 weeks of paper trading with stratification:

- **HIGH confidence cohort** (>0.65): Win rate 58%, Sortino 1.4. Marginal but real edge after fees.
- **MEDIUM confidence cohort** (0.45-0.65): Win rate 51%, Sortino 0.3. Noise. Not worth trading.
- **LOW confidence cohort** (<0.45): Win rate 47%, Sortino -0.2. Slight negative edge — correctly identified as low-quality.

The system's confidence scores *are* somewhat calibrated — HIGH beats LOW consistently. But the edge is thin, and MEDIUM is indistinguishable from random. Our current approach: only auto-trade HIGH confidence convictions, flag MEDIUM for manual review, ignore LOW.

---

## 4. Daily Operational Cadence

### 4.1 System Timing

| Cycle | Interval | What Happens |
|-------|----------|-------------|
| Brain synthesis | 15 min | All active producers polled, signals synthesized, convictions emitted |
| Full sweep | 6 hours | Deep analysis across all domains, slower producers included |
| Resolver | 1 hour | Evaluate whether past convictions were correct (outcome labeling) |
| Dashboard refresh | Real-time | HTMX polling for latest state |

These are configured via:
```yaml
brain_interval_seconds: 900      # 15 min
brain_full_interval_seconds: 21600  # 6 hours
resolver_interval_seconds: 3600   # 1 hour
```

### 4.2 Daily Cockpit Review Checklist

We run through this every morning. Takes 5-10 minutes on the dashboard:

**1. Producer Health**
- How many producers are active vs `no_source_configured`?
- Any producer with last-emit > 2 hours ago? (Stale signal source)
- Minimum 3 domains contributing to synthesis?

**2. Conviction Quality**
- What was the top conviction from last 24h?
- Is confidence distribution healthy (spread across LOW/MED/HIGH) or clustering near 0.5?
- Any convictions with magnitude > 7? (Strong signal — pay attention)

**3. Open Positions**
- Current PnL on each position (fetched from latest mark price, not stale entry data)
- Are any positions approaching stop levels?
- Any position open > 48h without hitting target or stop? (Time-based review trigger)

**4. Domain Coverage**
- Which domains contributed to last cycle? (TA, on-chain, sentiment, TradFi, orderbook)
- If < 3 domains active, consider suspending auto-trading

**5. Benchmark Comparison**
- How does today's PnL compare to the four benchmarks?
- Any benchmark outperforming the full system over the last 7 days? (Red flag)

### 4.3 Kill Switch Criteria

The kill switch halts all auto-trading. It triggers on:

| Condition | Threshold | Rationale |
|-----------|-----------|-----------|
| Portfolio drawdown | > configured max (we use 10%) | Capital preservation |
| Consecutive losing trades | > 5 in a row | Possible regime change or system bug |
| Data quality | < 50% of producers healthy | Synthesis inputs too thin |
| Cycle age | Last brain cycle > 30 min ago | System may be crashed/hung |
| Domain coverage | < 3 active domains | Not enough signal diversity |

When the kill switch triggers:
1. All pending orders cancelled
2. No new positions opened
3. Existing positions keep their stops (don't close everything — that's panic, not risk management)
4. Alert sent to operator
5. Manual review required before re-enabling

### 4.4 Sustainability and Burnout Prevention

Running a signal system 24/7 is operationally exhausting if you try to monitor it manually. Key sustainability practices:

**Automate the boring stuff:** Producer health checks, benchmark comparison, and kill switch logic should all be automated. You should only need to look when something's wrong.

**Alert on exceptions, not on normals:** Don't get a notification every 15 minutes that the brain cycled. Get a notification when it *didn't* cycle, or when a conviction exceeds threshold, or when a benchmark starts winning.

**Weekly retrospective, not daily panic:** The daily cockpit check is a 5-minute scan. The real analysis happens weekly: review stratification data, check benchmark trends, evaluate whether to adjust weights or thresholds. Don't tweak parameters daily — that's overfitting to noise.

**Log everything, query later:** Every conviction, every trade, every producer emit goes into SQLite. When something goes wrong (and it will), you want the forensic trail. We've diagnosed every failure mode in Section 2 by querying historical events.

---

## 5. Architecture Reference

For builders starting from scratch, here's the minimal viable signal benchmarking loop:

```
Producers (N data sources)
    ↓ emit typed events
SQLite events table
    ↓ read by
Brain Orchestrator (synthesis every K minutes)
    ↓ emit convictions
Conviction table
    ↓ read by
OMS (paper mode) → Position table
    ↓ compared against
Benchmarks (flat, momentum, equal-weight, full system)
    ↓ evaluated by
Resolver (outcome labeling every hour)
    ↓ feeds
Stratification (confidence binning + FDR)
    ↓ informs
Weight/threshold adjustments (weekly)
```

The key insight: **the benchmarking infrastructure is not optional.** It's not something you add after the system "works." Without benchmarks from day one, you have no way to know if the system works. You're just watching numbers move and telling yourself a story.

---

## Conclusion

Building a signal aggregation system is the easy part. Proving it has edge is hard. The four benchmarks force intellectual honesty: beat cash, beat dumb momentum, beat naive averaging, and only then claim your sophisticated synthesis adds value.

The failure modes are unglamorous — string mismatches, inverted math, silent exceptions, missing null checks. They don't make for exciting war stories. But each one silently corrupted our results for days or weeks before detection. The cumulative effect of undetected bugs in a trading system isn't gradual degradation — it's complete loss of epistemic grounding. You think you're learning from your results, but your results are artifacts of bugs.

Monitor your producers. Stratify your convictions. Apply FDR correction. And never, ever let a neutral conviction default to long.

---

*Built with b1e55ed — a continuous signal benchmarking system for crypto oracles. [github.com/P-U-C/b1e55ed](https://github.com/P-U-C/b1e55ed)*
