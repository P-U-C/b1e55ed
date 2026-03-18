# b1e55ed × x402: Integration Plan (Roadmap — Deferred)

> Branch: `feat/x402-payment-analysis`
> Status: Design complete. Implementation deferred until post-falsification.

---

## Decision

x402 is the right monetization layer for b1e55ed. It is not the right thing to build now.

**The rule:** Signal consumption should be paid for only when signals are proven valuable.
Charging for alpha before proving you have alpha is backwards.

**The gate:** The 50-trade falsification test must pass first.
High-confidence forecasts must statistically outperform low-confidence forecasts net of fees.
When that proof is on-chain and public, x402 gets switched on.

---

## What x402 Is

HTTP 402 "Payment Required" — an open standard by Coinbase. Server returns 402 with payment details. Client (agent) pays on-chain in USDC, retries with proof in header. No accounts, no API keys, no manual flows. One middleware decorator on the server. One function call on the client.

```python
# Server: one decorator
@x402_required(price="0.001 USDC", network="ethereum")
async def get_forecasts(): ...

# Client: one function (agents call this autonomously)
import x402
forecasts = x402.get("https://oracle.b1e55ed.permanentupperclass.com/api/v1/forecasts")
```

---

## Why NOT a Production Gate

Signal *submission* (producers paying to submit) was considered and rejected.

Karma already provides the correct Schelling point for producer quality:
- Being wrong costs producers weight and influence — a compounding reputational cost
- A flat per-submission fee is a weaker signal than outcome-weighted reputation
- It would create a bootstrap problem: new producers need karma to prove value but must pay to generate karma
- The people most deterred by a fee are genuine new contributors, not noise-bots

**Conclusion:** Never gate signal production. Karma is the mechanism.

---

## The Right Gate: Signal Consumption

External agents querying conviction scores are the correct x402 target:
- They're consuming value (proven alpha), not producing it
- They can evaluate whether the price is worth it (track record is on-chain)
- It doesn't create bootstrap friction for producers
- It aligns incentives: the better our signals, the more agents pay, the more we can invest in infrastructure

---

## Phased Rollout

### Phase 0 — Now (Free, Build Trust)
- All endpoints free
- Accumulate falsification data
- Get agents using the API
- ERC-8004 manifest: `"x402Support": false`

### Phase 1 — Post-Falsification (Consumption Gate)
**Trigger:** 50-trade falsification test passes with statistical significance.

```bash
# Free tier (always)
curl https://oracle.b1e55ed.permanentupperclass.com/api/v1/forecasts?confidence=low

# Paid tier (x402 gate)
curl https://oracle.b1e55ed.permanentupperclass.com/api/v1/forecasts
# → 402 Payment Required: $0.001 USDC per query

# x402 agent client handles this automatically:
forecasts = x402.get("https://oracle.b1e55ed.permanentupperclass.com/api/v1/forecasts")
```

ERC-8004 manifest updated: `"x402Support": true` — discoverable by any agent ecosystem.

### Phase 2 — Revenue Sharing
Karma holders earn a percentage of consumption fees:
```
producer_share = (producer_karma / total_karma) × period_revenue
```
Creates producer retention flywheel: good producers earn passive income from signal consumption. The system becomes self-sustaining.

### Phase 3 — Tiered Access

| Tier | Endpoint | Price | What You Get |
|---|---|---|---|
| Free | `/forecasts?confidence=low` | $0 | Raw signals, no scoring |
| Standard | `/forecasts` | $0.001/query | Conviction scores + direction |
| Premium | `/forecasts/context` | $0.01/query | Full synthesis context, regime, producer attribution |
| Stream | `/forecasts/stream` | $10/month | Real-time webhook, sub-100ms latency |
| Free (ERC-8004 identity) | All tiers | Free up to 100/day | Verified agents with on-chain identity get free tier |

---

## Technical Implementation (When Ready)

**Server side (Python + FastAPI):**
```python
pip install x402
```
One middleware call on the FastAPI app. That's it.

**The ERC-8004 connection:**
When x402 is live, the producer manifest JSON gets `"x402Support": true`. Any agent reading the Identity Registry on Ethereum mainnet discovers that b1e55ed signals are available for programmatic purchase. No human needed to find us — discovery is on-chain, payment is on-chain, signals flow automatically.

**Payment wallet:** Oracle server's `agentWallet` set in ERC-8004 Identity Registry → that's where payments land. Full circle: identity, reputation, and payment all flow through the same on-chain identity.

---

## Why This Is the Right Business Model

1. **Aligns with product truth:** You only pay for signals when they've been proven to have edge. The falsification test is the credibility gate.

2. **Doesn't tax producers:** All friction is on the consumption side. Producers have zero cost to participate.

3. **On-chain native:** x402 + ERC-8004 means the entire loop (identity → signal → payment → reputation) is on-chain-legible without requiring anyone to trust us.

4. **Composable:** Any agent that reads the Identity Registry on Ethereum mainnet can discover, pay for, and consume b1e55ed signals without us doing anything. The protocol handles it.

---

## What Goes in This Branch

This branch holds the design doc only. No code changes.

When Phase 1 is triggered (falsification test passes):
- PR off this branch with `x402` middleware added to `api/main.py`
- ERC-8004 manifest `x402Support` field flipped to `true`
- One-line change to oracle's Identity Registry `setMetadata()` call
