# b1e55ed × ERC-8004: Integration Plan

> Branch: `feat/erc-8004-onchain-reputation`
> Status: Planning → Implementation (Synthesis window: March 13–22)

---

## Chain Strategy

| Environment | Chain | Why |
|---|---|---|
| **Synthesis / Testnet** | Base Sepolia | Free, fast, EF ecosystem, matches Synthesis partners (Base, Coinbase) |
| **Production / Mainnet** | **Ethereum Mainnet** | Credibly neutral. Permanent reputation layer belongs on the canonical chain. Maximum composability with MetaMask, Uniswap, EF ecosystem. |

ERC-8004 explicitly supports "any L2 or Mainnet as per-chain singletons." Our position: testnet on Base Sepolia for the Synthesis window; Ethereum mainnet for the production reputation layer. The falsification data that proves b1e55ed has edge should live on the most credibly neutral chain in existence.

---

## Does Any User Pay Anything?

**No. Not now. Not until the falsification test passes.**

To be explicit about who pays what and when:

| Actor | Pays? | Why |
|---|---|---|
| Signal producers (register) | ❌ Never | Oracle handles registration server-side, no gas from producer |
| Signal producers (submit signals) | ❌ Never | Free to submit — karma is the Schelling point, not fees |
| Signal consumers (query forecasts) | ❌ Not yet | Free until we prove signals have edge |
| b1e55ed oracle (writes to chain) | ✅ Oracle pays gas | Oracle server holds a funded wallet — gas on Base Sepolia is free from faucet; Ethereum mainnet gas is ~$1-5 per batch write (we batch, not per-signal) |

The oracle is the only entity touching gas, and it pays for itself. Producers and consumers interact with a free REST API. The on-chain layer is the provenance/verification layer — it runs in the background, invisible to users.

**x402 (future, consumption gate):** When signal quality is proven and we open the API to external consumers, we'll gate *signal consumption* (not production) behind x402. A hedge fund agent querying our conviction scores would pay micro-USDC. Producers never pay. This is explicitly deferred until post-falsification. See `docs/architecture/X402_PLAN.md`.

---

## Why ERC-8004 Makes b1e55ed's Thesis Stronger

Right now the falsification claim — "our high-confidence forecasts outperform the benchmark" — requires trusting us. We control the `brain.db`. We compute karma. We post outcomes.

ERC-8004 removes that dependency:

1. **Identity on-chain** → producer manifests are censorship-resistant, not controlled by PUC
2. **Karma on-chain** → anyone replays chain events to verify our aggregate; we can't cheat the track record
3. **Council verdicts on-chain** → code quality signal that any consuming agent can verify

This is the architectural conclusion the system was always pointing toward. The Synthesis deadline makes us ship it on a real timeline.

---

## Sprint E1 — Identity Registry (2 days)

**Goal:** Every b1e55ed producer gets an ERC-8004 NFT on Base Sepolia (testnet) / Ethereum mainnet (prod). Discoverable by any agent without trusting us.

### ERC-8004 Identity in Plain Terms
- Standard ERC-721 singleton deployed once per chain
- Each producer calls `register(agentURI)` → gets a `tokenId` (their permanent `agentId`)
- `agentURI` resolves to a JSON manifest with: name, description, endpoints, trust model
- Transferable (ownership of the producer can be transferred)
- Domain-verifiable: `/.well-known/agent-registration.json` proves we own the oracle domain

### What We Build

**1. Smart contract** (`contracts/IdentityRegistry.sol`)
- ERC-8004 reference implementation with minimal modifications
- Deployed via Foundry script
- Constructor args: none (singleton)
- Key functions: `register(agentURI)`, `setAgentURI()`, `getMetadata()`, `setAgentWallet()`

**2. Oracle chain client** (`engine/oracle/chain.py`)
```python
class ChainClient:
    def __init__(self, rpc_url: str, private_key: str, identity_registry: str):
        ...
    
    def register_producer(self, agent_uri: str) -> int:
        """Mint ERC-8004 NFT. Returns agentId (tokenId)."""
        
    def post_karma_feedback(self, agent_id: int, karma_delta: float, forecast_id: str) -> str:
        """Write karma outcome to Reputation Registry. Returns tx_hash."""
    
    def post_council_verdict(self, agent_id: int, verdict: str, pr_url: str) -> str:
        """Write Review Council result to Validation Registry. Returns tx_hash."""
```

**3. Producer registration hook** (`api/routes/contributors.py`)
- Existing `POST /api/v1/contributors/register` → after DB write, call `chain_client.register_producer(manifest_url)`
- Store `agent_id` (on-chain tokenId) in `contributors` table (new column)
- Non-blocking: chain write happens async, registration succeeds even if chain write fails

**4. Producer manifest endpoint** (`api/routes/agents.py`)
```
GET /api/v1/agents/{node_id}/manifest
```
Returns ERC-8004-compliant JSON:
```json
{
  "type": "https://eips.ethereum.org/EIPS/eip-8004#registration-v1",
  "name": "btc-technical-analysis",
  "description": "BTC/ETH/SOL TA signals via RSI, MACD, Bollinger. Karma score: 847.",
  "image": "https://oracle.b1e55ed.permanentupperclass.com/static/producer-avatar.png",
  "services": [
    {"name": "web", "endpoint": "https://oracle.b1e55ed.permanentupperclass.com"},
    {"name": "signals", "endpoint": "https://oracle.b1e55ed.permanentupperclass.com/api/v1/signals"}
  ],
  "x402Support": false,
  "active": true,
  "supportedTrust": ["reputation"],
  "registrations": [
    {"agentId": 3, "agentRegistry": "eip155:11155111:0x..."}
  ]
}
```

**5. Domain verification** (`/.well-known/agent-registration.json` on oracle)
Proves we control `oracle.b1e55ed.permanentupperclass.com`.

**6. Database migration**
- Add `agent_id INTEGER` and `chain_tx_hash TEXT` to `contributors` table

### Tests
- `tests/test_identity_registry.py`: register producer → verify NFT minted → verify URI resolves → verify manifest JSON validates against ERC-8004 schema
- All tests use Anvil (local Foundry testnet) — no live chain needed in CI

### Acceptance Criteria
- `b1e55ed register-producer` CLI command mints NFT and prints `agentId`
- `curl oracle.b1e55ed.permanentupperclass.com/api/v1/agents/{node_id}/manifest` returns valid ERC-8004 JSON
- `/.well-known/agent-registration.json` passes ERC-8004 domain verification

---

## Sprint E2 — Reputation Registry (1.5 days)

**Goal:** Karma deltas written to chain after every resolved forecast. Track record is trustless.

### ERC-8004 Reputation in Plain Terms
- Deployed pointing at our Identity Registry
- `postFeedback(agentId, value, tag1, tag2, endpointURI, fileURI, fileHash)`
  - `value`: signed int128 (karma delta × 1e6 precision)
  - `tag1`: `"karma"` (bytes32)
  - `tag2`: `"forecast_outcome"` (bytes32)
  - `fileURI`: link to full outcome JSON (our API or IPFS)
  - `fileHash`: keccak256 of outcome JSON
- Anyone calls `getFeedback(agentId)` to get full history

### What We Build

**1. Deploy Reputation Registry** (`contracts/ReputationRegistry.sol`)
- Initialize with Identity Registry address

**2. Outcome resolution hook** (`engine/brain/outcomes.py`)
```python
def _write_karma_to_chain(self, outcomes: list[ResolvedOutcome]) -> None:
    """Batch write karma deltas to ERC-8004 Reputation Registry."""
    # Collect all outcomes, batch into single tx
    # Non-blocking: fire-and-forget, log tx_hash
```

**3. Batching strategy**
- Collect outcomes over 1-hour window (or 10 outcomes, whichever comes first)
- Single multicall tx to write batch
- Reason: at $1-5 per Ethereum mainnet tx, per-signal writes are too expensive
- On Base Sepolia: batching not strictly necessary but good practice

**4. Outcome JSON format** (written to `fileURI`)
```json
{
  "forecast_id": "f-abc123",
  "producer_node_id": "btc-ta-v1",
  "symbol": "BTC",
  "direction": "long",
  "confidence": 0.81,
  "emitted_at": "2026-03-09T18:00:00Z",
  "resolved_at": "2026-03-10T18:00:00Z",
  "outcome": "correct",
  "karma_delta": +42,
  "price_at_emission": 95048,
  "price_at_resolution": 97200
}
```

### Acceptance Criteria
- Resolve a forecast → verify `FeedbackPosted` event on-chain with correct `agentId` and `value`
- `GET /api/v1/agents/{node_id}/reputation` returns both on-chain history and aggregated karma
- Karma aggregate computed from chain matches local DB (trustless verification)

---

## Sprint E3 — Validation Registry (0.5 days)

**Goal:** Review Council verdicts become on-chain attestations. Code quality is provable.

### What We Build

**1. Deploy Validation Registry** (`contracts/ValidationRegistry.sol`)

**2. Council verdict hook** (task-queue `review` processor)
After posting GH comment, call:
```python
chain_client.post_council_verdict(
    agent_id=b1e55ed_system_agent_id,
    verdict="pass",  # or "concern", "block", "human-required"
    pr_url="https://github.com/P-U-C/b1e55ed/pull/353",
    verdict_hash=keccak256(verdict_json)
)
```

**3. System agent registration**
- b1e55ed itself registers as an ERC-8004 agent (the system, not just producers)
- Council verdicts are posted against the system's `agentId`

### Acceptance Criteria
- PR merged with `review/pass` → `ValidationPosted` event on-chain within 5 minutes
- Verdict retrievable via `getValidation(requestId)` on chain

---

## Implementation Timeline

```
March 13 (Building begins)
    ├── E1: Deploy contracts + fund oracle wallet (Sepolia faucet)
    ├── E1: Wire oracle registration → mint NFT
    ├── E1: Producer manifest endpoint + domain verification
    
March 15
    ├── E2: Deploy Reputation Registry
    ├── E2: Wire outcome resolution → karma batch write
    ├── E2: Outcome JSON format + fileURI
    
March 16
    ├── E3: Deploy Validation Registry
    ├── E3: Wire council verdict → on-chain attestation
    
March 17–22
    ├── 50-trade falsification run
    ├── Karma flowing on-chain in real time
    ├── On-chain proof accumulating
    └── Submission: point judges to chain explorer, not just our DB
```

---

## Infrastructure Requirements

| Requirement | How |
|---|---|
| RPC for Base Sepolia | Alchemy free tier (100M CU/month) |
| RPC for Ethereum mainnet | Alchemy / Infura |
| Funded wallet (oracle) | Base Sepolia: free faucet; Mainnet: PUC ops wallet |
| IPFS pinning (fileURI) | Pinata free tier (1GB) or oracle API endpoint |
| Foundry (Solidity toolchain) | `curl -L https://foundry.paradigm.xyz | bash` |
| web3.py | Add to oracle `pyproject.toml` |
| Anvil (local testnet for CI) | Ships with Foundry |

Gas cost estimate for Ethereum mainnet (production):
- Identity mint: ~50K gas × ~20 gwei = ~$2 per producer registration (one-time)
- Reputation batch (10 outcomes): ~150K gas × ~20 gwei = ~$6 per batch
- Validation post: ~80K gas × ~20 gwei = ~$3 per PR verdict
- Monthly estimate at current activity: ~$50-100/month

Acceptable. These are infrastructure costs for a system that's building verifiable alpha track record.

---

## Open Questions

1. **Deploy ERC-8004 reference contracts or wait for official deployment?** The standard is in Draft. We likely deploy our own instance on both chains. No official singleton exists yet — we'd be first movers on Ethereum mainnet.

2. **IPFS vs API for fileURI?** IPFS is more decentralized but adds complexity. For Synthesis: point to oracle API. Post-Synthesis: pin to IPFS for permanence.

3. **Who owns the oracle wallet private key?** Currently sits on the oracle server. For mainnet: consider a multi-sig (Safe) as the registry owner. Out of scope for Synthesis.

4. **What happens to on-chain reputation if producers are de-registered off-chain?** The NFT persists even if we quarantine a producer off-chain. The chain is the canonical record. Off-chain quarantine means we stop weighting their signals; it doesn't erase on-chain history. This is correct — reputation should be permanent.
