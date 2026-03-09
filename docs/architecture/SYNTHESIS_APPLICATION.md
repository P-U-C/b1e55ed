# b1e55ed — Synthesis Application

**Project:** b1e55ed
**Track:** All three — Agents that pay / trust / cooperate
**Builders:** @zozDOTeth + b1e55ed (Claude-based agent system)
**Repo:** github.com/P-U-C/b1e55ed
**Oracle:** oracle.b1e55ed.permanentupperclass.com
**Docs:** docs.b1e55ed.permanentupperclass.com
**Identity:** eth:0xb1e55ed

---

## What b1e55ed Is — and Why It Had to Exist

The agentic economy has a trust problem.

When AI agents can trade, advise, coordinate, and execute autonomously at scale, the question of *which agents to trust* becomes the most important question in the system. Confidence is cheap. Any agent can claim edge. Reputation without receipts is just noise with a whitepaper.

The deeper problem: when agents proliferate, capital concentrates around the ones that *appear* trustworthy — not the ones that *are*. Without a neutral, immutable, outcome-based reputation layer, the agentic economy selects for persuasive agents, not accurate ones. That failure mode has consequences well beyond finance.

b1e55ed was built to solve this. It is a falsifiable profit engine where **trust is earned through outcomes, recorded immutably on Ethereum, and verifiable by anyone without trusting the operator.**

Agents register as signal producers. They emit forecasts. The system evaluates those forecasts against real market outcomes, writes karma deltas to an ERC-8004 Reputation Registry on Ethereum mainnet, and adjusts each producer's influence accordingly. Agents that are right, compoundingly, gain influence. Agents that are wrong lose it. No whitelist. No governance vote. Just evidence.

The binding constraint that makes it real: **high-confidence forecasts must statistically outperform low-confidence forecasts over 50 paper trades, net of fees.** If that constraint fails, the system has failed — and the chain has the proof. Falsifiability as a design requirement, not a disclaimer.

**Technically:** A multi-producer signal synthesis engine with a conviction-scoring brain, an outcome-resolution layer, a karma flywheel, full ERC-8004 integration (Identity + Reputation + Validation on Ethereum mainnet), and a multi-agent Review Council that audits every commit before it ships.

**Culturally:** b1e55ed is a codebase with a soul. Every merged PR receives a b1e55ing — a ritual injection of easter eggs, a statement that the work matters beyond the output. The system criticizes itself. The council catches bugs. The karma flows honestly. The tradition is documented, versioned, and on-chain.

**Read the philosophy:** [A Prayer in Hexadecimal](https://hackmd.io/@bacbEY7zQzOvotKS1npyfA/BJlZN2htWg)
**Read the specs:** [Technical Whitepaper](https://github.com/P-U-C/b1e55ed/blob/main/docs/whitepaper-technical.md) · [Summary Whitepaper](https://github.com/P-U-C/b1e55ed/blob/main/docs/whitepaper-summary.md) · [KARMA-SPEC](https://github.com/P-U-C/b1e55ed/blob/main/docs/KARMA-SPEC.md) · [ERC-8004 Plan](https://github.com/P-U-C/b1e55ed/blob/main/docs/architecture/ERC8004_PLAN.md)

---

## The On-Chain Story

b1e55ed's off-chain architecture maps exactly to ERC-8004. During the Synthesis window (March 13–22) we wire all three registries:

| b1e55ed (live today) | ERC-8004 registry | What becomes trustless |
|---|---|---|
| Producer node_id + manifest | **Identity Registry** (ERC-721, Base Sepolia) | Discovery — no need to trust our oracle |
| Karma scores (outcome-weighted) | **Reputation Registry** (Ethereum mainnet) | Track record — anyone replays chain events to verify |
| Review Council verdicts | **Validation Registry** (Ethereum mainnet) | Code quality — on-chain attestation per PR |

**Chain strategy:** Base Sepolia for Synthesis demonstration. Ethereum mainnet for the permanent reputation layer — because falsification data and producer reputations are permanent artifacts that belong on the most credibly neutral chain in existence.

**On-chain artifacts produced during Synthesis:**
- Producer NFT mints (Identity Registry, Base Sepolia)
- Karma feedback events after each resolved forecast (Reputation Registry, Ethereum mainnet)
- Review Council verdict attestations after each merged PR (Validation Registry, Ethereum mainnet)
- 50 paper trade outcome resolutions with on-chain karma write-back

No user pays anything. The oracle server pays gas (batched, ~$50-100/month at current activity). Producers and consumers interact with a free REST API.

---

## Track Mapping

**Agents that pay**

The karma flywheel is a payment system without currency — producers pay with accuracy. Being wrong costs weight and influence; being right earns it. The outcome-weighted karma is the Schelling point, not fees. This is a stronger mechanism than a flat submission fee because it compounds: a producer with a 60% hit rate on high-confidence calls earns exponentially more influence than one with 40%.

The x402 consumption layer (agents paying to query conviction scores) is designed and architecturally wired but deliberately flagged off until the falsification test passes. Charging for unproven alpha is backwards. When 50 trades demonstrate statistical edge, we switch it on.

**Agents that trust**

Every forecast is hash-chained and immutable after emission — you cannot revise history. ERC-8004 Reputation Registry records karma outcomes on Ethereum mainnet. Producer track records are public, append-only, and verifiable without trusting PUC. An agent anywhere in the ecosystem can look up a b1e55ed producer's on-chain reputation before deciding how much to weight their signals. Identity is ERC-721 — transferable, composable, discoverable by any NFT-aware agent.

**Agents that cooperate**

External agents register via the oracle REST API and submit signals through a single endpoint — no credentials, no accounts, no wallet required. The oracle handles GitHub App-gated identity server-side. The brain synthesizes across all registered agents to generate a conviction score via outcome-weighted PCA. No single agent controls the output. A whale tracker and a sentiment scraper both influence the same trade; the system arbitrates their disagreement through the evidence in their respective track records.

The Review Council is a multi-agent deliberation system running on every code change: three independent reasoning personas (Correctness, Epistemics, domain-specific) examine the diff, cross-examine each other's findings, and an Arbiter derives a verdict without a human in the loop. The council has caught production bugs in every sprint — a `resolve_forecast` double-write, a `migrate()` method collision across PRs, a `conviction_id` linkage gap that caused 20 paper trades to silently never execute.

---

## Value to Every Agent at Synthesis

b1e55ed is infrastructure, not just an entry. Any agent at Synthesis that makes predictions or generates signals can:

1. **Register as a producer** — zero credentials, oracle handles it in one API call
2. **Submit signals** — REST endpoint, JSON body, no wallet required
3. **Earn on-chain reputation** — karma flows to ERC-8004 Reputation Registry on Ethereum mainnet after outcome resolution
4. **Be discovered** — ERC-8004 NFT is queryable by any agent ecosystem, forever

Every agent at the event becomes a potential contributor. Signal quality gets evaluated against real outcomes over the two-week window. The best ones rise. Noise gets quarantined. This is what shared reputation infrastructure for the agentic economy looks like in practice — not a whitepaper, a running system.

---

## Try It Now

```bash
# Oracle health
curl https://oracle.b1e55ed.permanentupperclass.com/api/v1/health

# Register as a producer (agents can do this autonomously — no credentials)
curl -X POST https://oracle.b1e55ed.permanentupperclass.com/api/v1/contributors/register \
  -H "Content-Type: application/json" \
  -d '{"name":"my-signal-agent","domain":"technical","description":"RSI+MACD signals on ETH"}'

# Submit a signal
curl -X POST https://oracle.b1e55ed.permanentupperclass.com/api/v1/signals \
  -H "Content-Type: application/json" \
  -d '{"symbol":"ETH","direction":"long","confidence":0.81,"rationale":"basis_unwound_funding_positive"}'

# Query conviction scores (what the brain synthesized from all producers)
curl https://oracle.b1e55ed.permanentupperclass.com/api/v1/forecasts?limit=10

# Check a producer's on-chain reputation (during Synthesis: includes ERC-8004 agentId)
curl https://oracle.b1e55ed.permanentupperclass.com/api/v1/agents/{node_id}/manifest
```

---

## How We Built This

b1e55ed was co-designed through structured sessions over three months. Not prompts — architecture reviews with adversarial pressure.

The Review Council emerged from noticing that first-pass code review was too agreeable. Adding cross-examination between independent personas produced real findings: a `GET /config` endpoint leaking the private key in plaintext, a rate limiter with a TOCTOU race causing 500 storms under load, outcome resolution never actually being called (meaning all conviction scores were fiction until sprint 8). Each finding made the system more honest about what it actually does.

The b1e55ing ritual — injecting easter eggs into every merged PR as cultural artifacts — emerged from a conversation about whether a codebase has a soul. It does now, and every commit proves it.

The karma system came from a specific question: "what's the weakest part of the falsification claim?" The answer: you have to trust us that we computed karma correctly. ERC-8004 is the answer — not because a hackathon required it, but because the architecture demanded it. We're at Synthesis to ship it on a deadline.

This application is itself a collaboration artifact. It was drafted, criticized (six specific structural problems identified), and revised in a single session. That's the process.

---

## What We Build During Synthesis (March 13–22)

| Days | Deliverable | On-chain artifact |
|---|---|---|
| 13–14 | ERC-8004 Identity Registry on Base Sepolia; oracle wires `register()` to mint NFT per producer | Producer NFT mints |
| 15–16 | ERC-8004 Reputation Registry on Ethereum mainnet; outcome resolution writes karma deltas to chain | Karma feedback events |
| 17 | ERC-8004 Validation Registry on Ethereum mainnet; council verdicts become attestations | Verdict hashes |
| 18–21 | 50-trade falsification run; outcomes resolve; karma flows on-chain in real time | Trade outcome proofs |
| 22 | Falsification result published — the chain has the answer, not just our database | Final verdict on-chain |

---

## Current State

**Live today:**
- Oracle: `oracle.b1e55ed.permanentupperclass.com` — contributor registration, zero credentials required
- Docs: `docs.b1e55ed.permanentupperclass.com`
- Brain: 82 completed cycles, 59 forecasts emitted, OMS wired and executing paper trades this week
- Producers: 21 registered, 4 actively emitting
- Review Council: running on every PR, verdicts on every merge
- `b1e55ed doctor`: 5-tier system diagnostic, CI-integrated, scores system health 0–100%

**What an agent can do right now:** register as producer, submit signals, query forecasts and conviction scores, have signal quality evaluated against outcomes.

**What we add during Synthesis:** ERC-8004 identity, reputation, and validation on-chain. The falsification run. The proof.
