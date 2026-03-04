# b1e55ed — Signal Accountability for Capital Allocators

**The decisive test**: Do high-confidence forecasts produce better economic outcomes than low-confidence forecasts, net of fees? If yes, the system has edge. If no, it doesn't. b1e55ed is built to answer this question with machine-verifiable evidence — not P&L claims, not backtests, not trust.

Most trading systems give you a number and ask you to believe it. b1e55ed gives you a falsifiable hypothesis and the data to test it yourself.

---

## The Problem

You cannot verify most trading claims:
- which signals drove which trades
- whether confidence estimates are calibrated
- whether the edge is repeatable or a regime artifact

A fund reports 40% returns. A signal service claims 73% accuracy. A quant strategy backtests to Sharpe 2.1. These numbers share a defect: they are not falsifiable. The underlying attribution remains opaque.

Unverified edge is not edge. It is luck with a story attached.

---

## How b1e55ed Works

Every forecast is a precise, immutable claim: direction, confidence, horizon. Timestamped and stored in an append-only, hash-linked event store. Retroactive modification breaks the hash chain.

When the horizon resolves, the system scores the outcome. Every producer gets a Brier score — the proper scoring rule that rewards honest probability estimates, not just directional accuracy. A forecaster claiming "70% confident" should be correct 70% of the time. The Brier score measures whether they are.

Producers accumulate karma based on whether their signals contributed to profitable trades. Karma uses an exponential moving average — consistently correct producers rise, consistently wrong producers fall, random producers drift neutral.

When the system synthesizes signals, it weights producers by karma. When it deploys capital, it deploys proportionally to demonstrated skill. The feedback loop closes. The system compounds.

---

## What You Can Verify

Before allocating capital, query any producer's:
- Directional accuracy by regime
- Brier calibration score
- Karma history (synthesis contribution to profitable trades)
- Track record under identical fee and slippage assumptions

The oracle serves these records from the same append-only log that drives the engine. You audit the same data the system trades on.

---

## The Proof Standard

Most systems benchmark against buy-and-hold. We benchmark against doing nothing.

Four benchmarks b1e55ed must beat:
1. **Flat/no-trade** — zero exposure
2. **Naive momentum** — buy above 20-day MA, sell below
3. **Equal-weight ensemble** — average all signals equally
4. **Discretionary human** — manual override

Beat all four. Same fees. Same slippage. Same data. Or no edge claim.

---

## Current Status

b1e55ed v1.0.0-beta.8 is in data accumulation. Forecasts are being emitted, attributed, and scored. The meta-producer activates at 500 resolved outcomes (~3–4 weeks with 13 producers across BTC, ETH, SOL).

What is live: forecast emission, Brier scoring, karma attribution, outcome resolution, oracle.

What is not yet proven: that the system beats all four benchmarks at scale.

We are building the proof, not asserting it.

---

## For Signal Producers

Your track record is portable and verifiable for the first time.

Karma is your on-chain CV. Every forecast is attributed, scored, and visible via the oracle. When your signals contribute to profitable trades, your karma rises. When the system deploys capital, it deploys proportionally to karma.

You don't need to trust us. You can audit your own attribution.

---

## Contact

[Placeholder — contact details pending]
