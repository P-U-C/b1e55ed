# b1e55ed — Signal Accountability for Capital Allocators

**One sentence**: b1e55ed is the first systematic trading system where every claimed edge is independently verifiable before you allocate a dollar.

---

## The Problem

Most trading systems give you a P&L and ask you to trust it. You cannot verify:
- which signals drove which trades
- whether the system's confidence estimates are calibrated
- whether the edge is repeatable or a regime artifact

You are buying a black box.

A fund reports 40% returns. A signal service claims 73% accuracy. A quant strategy backtests to Sharpe 2.1. These numbers share a defect: they are not falsifiable. The underlying attribution—which signals contributed, whether stated confidence matched realized accuracy, whether the system caught skill or a favorable regime—remains opaque.

This is not a disclosure problem. It is a structural one. Unverified edge is not edge. It is luck with a story attached.

---

## How b1e55ed Works

Every forecast b1e55ed emits is a precise, immutable claim: direction, confidence, horizon. It cannot be modified. It is timestamped and stored in an append-only, hash-linked event store. Retroactive modification breaks the hash chain and is detectable on any replay.

When the horizon resolves, the system checks whether the forecast was correct. Every producer gets a Brier score—the proper scoring rule used by professional forecasters because it rewards honest probability estimates, not just directional accuracy. A forecaster who says "70% confident" should be correct 70% of the time. The Brier score measures whether they are.

Producers also accumulate karma based on whether their signals contributed to profitable trades. Karma uses an exponential moving average that weights recent outcomes while retaining historical memory. Consistently correct producers rise. Consistently wrong producers fall. Random producers drift toward neutral.

When the system synthesizes signals into a trading decision, it weights producers by karma. When it deploys capital, it deploys proportionally to demonstrated skill. The feedback loop closes. The system compounds.

---

## What You Can Verify

Before allocating capital, you can query any producer's:
- Directional accuracy by regime
- Brier calibration score
- Karma history (synthesis contribution to profitable trades)
- Track record under the same fee and slippage assumptions as live trading

This is not self-reported. The oracle serves these records from the same append-only log that drives the engine. You audit the same data the system trades on.

---

## The Proof Standard

Most systems benchmark against buy-and-hold. We benchmark against doing nothing.

The four benchmarks b1e55ed must beat:
1. **Flat/no-trade** — zero exposure. If the system can't beat this, it's destroying value.
2. **Naive momentum** — buy above 20-day MA, sell below.
3. **Equal-weight ensemble** — average all producer signals equally.
4. **Discretionary human** — zoz's manual override.

Beat all four. Under the same fees. Same slippage. Same data source. Or the engine doesn't claim edge.

---

## Current Status

b1e55ed v1.0.0-beta.8 is in data accumulation phase. The engine is running. Forecasts are being emitted, attributed, and scored. The meta-producer—the system's highest-order signal—activates at 500 resolved outcomes (~3–4 weeks of operation with 13 producers running across BTC, ETH, SOL).

What is live: forecast emission, Brier scoring, karma attribution, outcome resolution, oracle.

What is not yet proven: that the system beats all four benchmarks at scale.

We are building the proof, not asserting it.

---

## For Signal Producers

Your track record is portable and verifiable for the first time.

Karma is your on-chain CV. Every forecast you submit is attributed, scored, and visible via the oracle. When your signals contribute to profitable trades, your karma rises. When the system deploys capital, it deploys proportionally to karma.

You don't need to trust us. You can audit your own attribution.

---

## Contact / Next Steps

[Placeholder — contact details pending]
