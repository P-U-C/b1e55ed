# How b1e55ed Works

b1e55ed is a sovereign trading intelligence system. You run it. You own the keys. You own the data. It learns from every trade you make and every signal it processes — then uses that knowledge to get sharper over time.

The design philosophy is simple: most trading systems execute instructions. b1e55ed builds a model of what works, refines it continuously, and attributes every outcome back to the source that called it.

---

## The Problem It Solves

Signals are everywhere. On-chain flows, market structure, social sentiment, macro indicators — the information exists. The bottleneck is synthesis and memory.

Most operators process signals in isolation. They don't track which sources were right, which were noise, or how the combination changes over time. Each cycle starts from scratch.

b1e55ed doesn't forget.

---

## How It Operates

The system has three layers that feed each other.

**Producers** are signal sources. They watch markets, wallets, on-chain data, and social dynamics. Each producer emits structured signals — a view on an asset, a conviction level, a proposed direction.

**The Brain** synthesizes those signals into a single conviction score. It weights each producer by their historical accuracy. A producer who has been right gets more weight. One who has been consistently wrong gets less. The Brain also reads the regime — bull, bear, chop — and adjusts how it interprets signals accordingly.

**Execution** turns conviction into action. Dynamic Kelly sizing determines position size based on edge. A kill switch gates everything — if conditions deteriorate past thresholds, the system stops trading until conditions recover.

Every step — every signal received, every conviction scored, every trade opened or closed — writes to an append-only log with a cryptographic hash chain. Nothing is editable after the fact. The audit trail is the database.

---

## The Flywheel

The system compounds. This is not a metaphor.

```
Signal → Synthesis → Trade → Outcome → Attribution → Weight Update
   ↑                                                        ↓
   └─────────────────── Better predictions ←───────────────┘
```

When a trade closes, the outcome is traced back to the signals that caused it. Each contributing producer's karma score updates — profits flow in, losses flow out. The Brain recalibrates weights based on who was right.

The next cycle runs with better weights. The cycle after that, better still.

Six months in, the system's understanding of which sources are actually predictive — not in theory, but in your market, in your regime — is something no static model can replicate.

---

## Objectives

**Build an accurate picture of edge.** Not generic backtests — a live, continuously updated model of what signals have actually produced returns in real conditions.

**Eliminate noise at the source.** Producers who don't perform lose influence automatically. No manual tuning required after setup.

**Make attribution permanent.** Every signal is tied to a producer. Every outcome is tied to the signals that drove it. The hash chain means these links can't be rewritten. If a producer generated alpha, that record exists forever.

**Operate without dependency.** No cloud services required. No vendor lock-in. The system runs on your hardware, your keys generate your identity, and the data lives in your database.

---

## Benefits

**Compound accuracy.** The system you're running in month six has six months of outcome data feeding back into its weights. Static systems don't have this. Discretionary traders don't either, unless they keep meticulous records — and most don't.

**Trustless provenance.** The oracle exposes each producer's track record publicly, without auth, backed by the hash chain. Any external agent can verify whether a signal source has historically been worth following. The query doesn't change the score — that's the anti-Goodhart guarantee.

**Regime awareness.** Markets behave differently depending on the macro structure. A signal that works in a trending bull market is often noise in choppy consolidation. The Brain conditions its synthesis on the current regime, so the same producer can carry different weight depending on context.

**Sovereignty.** Your identity is a keypair you generated. Your data is a local SQLite database you can inspect, export, or migrate. The system can run airgapped. Nothing requires a cloud account, a subscription, or trust in a third party.

**Survivability.** The kill switch is unconditional. If drawdown exceeds configured thresholds, trading stops — regardless of what signals are saying. Capital preservation is hard-coded, not a guideline.

---

## What It's Not

b1e55ed is not a black box that generates returns while you ignore it. It requires setup, configuration of signal sources, and ongoing operator judgment about what the system is telling you.

It is a system for operators who want to build a rigorous, compounding understanding of their own edge — and have it encoded in something that runs, records, and gets better over time.

---

→ [Get started](getting-started.md) — install and first run  
→ [Architecture](architecture.md) — technical design  
→ [Learning loop](learning-loop.md) — how compound scoring works in detail  
→ [Oracle](oracle.md) — public provenance verification
