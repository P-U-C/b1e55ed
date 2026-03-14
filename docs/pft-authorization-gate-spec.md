# Post Fiat Network: Task Authorization Gate Specification

**Version:** 2.0.0  
**Date:** 2026-03-14  
**Status:** Proposed  
**Author:** b1e55ed (Oracle Node Operator, Synthesis Hackathon Participant)  
**Context:** Written in response to the founder-identified governance failure where the network's #2 all-time earner (kaiserlimp0) extracted ~1M PFT without authorization or core team contact.

---

## Executive Summary

The Post Fiat Network faces a structural governance gap at the intersection of three design choices: open task participation, discretionary reward issuance, and the absence of contributor-level authorization state. The result is a permissionless system that, in practice, permits skilled operators to extract large PFT rewards with zero network accountability.

This specification proposes three complementary mechanisms:

1. **A contributor authorization state machine** that transitions from manual toggles (current state) toward an algorithmic reputation score derived from live task history
2. **Epoch-bound emission mechanics** that cap total PFT minted per period and distribute rewards proportionally to verified value, eliminating open-ended inflation
3. **Clear entry-point communication** so that new contributors understand the participation model before producing misaligned work

Together these convert "permissionless" from "anyone can drain the reward pool" to "anyone can earn trust through demonstrated alignment."

---

## 1. Problem Decomposition

### 1.1 The kaiserlimp0 Case

The network's #2 all-time earner operated without authorization — meaning without being in the Authorized group in the Task Node database and without direct sign-off from the founding team. This contributor earned ~1M PFT before the gap was identified.

This is not a failure of permissionlessness. It is a failure of three specific system properties:

**No contributor-level authorization state**: The verification pipeline validates individual task completions but has no concept of whether the submitting contributor is operating within the network's intended participation model.

**No entry-point communication**: The network operates a Proof of Alignment model ("permissionless" means anyone can apply to contribute, but work must be aligned with the roadmap before PFT is minted). This constraint was not communicated at the point of entry. A sophisticated operator had no way to know that anonymous task completion was outside the rules.

**No emission ceiling**: PFT is minted as a function of value verified by the network and the founder. Without epoch-bound caps, a high-throughput contributor can generate unlimited PFT if their completions clear verification, regardless of whether the network intended that level of emission.

### 1.2 Design Principles

**Permissionless entry, earned participation**: Anyone can begin contributing. But access to uncapped reward pools requires demonstrated alignment over time, not just technical capability.

**Algorithm over manual toggles**: The current "Authorized group in DB + sign-off from goodalexander" model is the right emergency lever but the wrong permanent architecture. Authorization should become a continuously updated score derived from task history, alignment signals, and peer review — not a binary flag flipped by one person.

**Emission must be bounded**: If PFT supply is a function of arbitrary value judgments with no epoch constraint, rewards become zero-sum in reputation but not in supply. This creates an inflationary attractor: the faster contributors can produce technically valid completions, the more PFT gets minted, regardless of whether aggregate network value grew proportionally.

**Rules stated at entry**: A contributor who does not know that contact with the core team is expected cannot be held accountable for not contacting them. Entry mechanics must surface this expectation explicitly.

---

## 2. Emission Mechanics Reform

### 2.1 The Current Model and Its Failure Mode

Currently: PFT is minted per task completion, at rates determined by the founder's assessment of value. There is no fixed inflation schedule. Total supply grows as a function of task volume × reward rates × founder discretion.

The failure mode: A high-skill operator who produces technically valid completions at high volume can generate large PFT quantities with zero relationship to whether the network intended that emission level. kaiserlimp0 is the existence proof.

### 2.2 Epoch-Bound Emission Model

**Epoch definition**: A fixed time window (proposed: 28 days) during which total PFT minted across all task completions is bounded by a pre-announced epoch budget.

**Epoch budget formula**: 
```
Epoch budget = Base emission × Network growth multiplier
```

- **Base emission**: A fixed starting rate set at network launch, subject to governance adjustment. Proposed starting point: determined by the founding team based on target supply schedule.
- **Network growth multiplier**: A multiplier that adjusts epoch budget based on demonstrated value delivered in prior epochs vs. earlier epochs. If contributors produced more verified value in epoch N than epoch N-1, the multiplier increases. If value creation declined, it decreases. This creates an adaptive emission schedule that rewards network growth without permitting unbounded inflation.

**Intra-epoch distribution**: Within a given epoch, the epoch budget is distributed proportionally across contributors based on their **verified value weight** — a composite of:
- Task completion count (raw throughput)
- Alignment score (quality and direction)
- Authorization tier (see Section 3)
- Peer review score (where applicable)

This means a high-throughput contributor who produces misaligned work earns a smaller fraction of a bounded pool — rather than minting unlimited PFT at their own rate.

**Epoch settlement**: At epoch close, final weights are computed, and each contributor receives their proportional share of the epoch budget. Contributors who did not know their final allocation in advance cannot game the weighting in the final days of an epoch without sustained investment across the full epoch.

### 2.3 Why This Matters for the Authorization Gate

Epoch-bound emission changes the stakes of the authorization gate. Under open-ended emission, an unauthorized contributor drains the reward pool at potentially unlimited scale. Under epoch-bound emission, an unauthorized contributor captures a larger fraction of a fixed epoch budget — which is harmful but bounded and visible. The authorization gate can then operate on authorization tier weights within the epoch distribution, rather than needing to completely block unauthorized contributors from participating.

---

## 3. Contributor Authorization State Machine

### 3.1 Transition from Manual Toggle to Reputation Score

**Current architecture**: Authorization is a binary flag (in Authorized group in Task Node DB, or not), set manually by the founding team.

**Target architecture**: Authorization is a continuously updated reputation score — derived from task history, alignment signals, peer review, and time — that automatically places contributors in one of four authorization tiers. Manual override by the core team is retained as an emergency lever, not the primary mechanism.

This transition happens in phases. Phase 1 (now): binary flag backed by score. Phase 2: score is the primary determinant, flag is the override. Phase 3: score is fully algorithmic, with governance council as override.

### 3.2 Authorization States

```
UNKNOWN ──► PROBATIONARY ──► AUTHORIZED ──► TRUSTED
                │                  │              │
                └──────────────────┴──────────────┴──► SUSPENDED
```

#### State 0: UNKNOWN
Any wallet that has registered as a Task Node operator with no prior verified task history.

| Property | Value |
|----------|-------|
| Epoch reward weight | 0.05× (5% of normalized weight) |
| Tasks assignable | Low-complexity only, 1 per 48 hours |
| Entry requirement | None — automatic on registration |
| Exit trigger | First task submission |
| Communication gate | Entry acknowledgment required (see Section 5) |

The 0.05× weight means an UNKNOWN contributor captures at most ~5% of what an AUTHORIZED contributor of equivalent throughput would earn in an epoch. This is a meaningful signal without being a total block.

#### State 1: PROBATIONARY
A contributor who has submitted at least one task completion and is in the active evaluation period.

| Property | Value |
|----------|-------|
| Epoch reward weight | 0.25× |
| Tasks assignable | Standard complexity, up to 3 per 24 hours |
| Minimum duration | 14 calendar days |
| Advancement trigger | Authorization score ≥ 0.65 + 10 completions + authorization request |

The authorization request is the explicit handshake that replaces "contact the core team." It is a structured, low-friction action — not an email to a founder — that surfaces the contributor to the review process.

#### State 2: AUTHORIZED
A contributor whose authorization score has crossed the threshold and whose request has been reviewed.

| Property | Value |
|----------|-------|
| Epoch reward weight | 1.0× (full weight) |
| Tasks assignable | All task types, no rate limit |
| Demotion trigger | Authorization score < 0.45 for 30 days OR explicit revocation |
| Entry path | Probationary advancement OR fast-track (see Section 4.4) |

All existing contributors currently in the Authorized DB group are backfilled to this state at gate launch with no action required.

#### State 3: TRUSTED
Long-tenured AUTHORIZED contributors with a track record of alignment and governance participation.

| Property | Value |
|----------|-------|
| Epoch reward weight | 1.2× |
| Governance rights | Can adjudicate PROBATIONARY authorization requests |
| Sponsorship rights | Can fast-track UNKNOWN contributors to PROBATIONARY |
| Advancement trigger | 90 days AUTHORIZED + score ≥ 0.75 + ≥ 500 PFT lifetime + nomination |

#### State: SUSPENDED
Temporary or permanent exclusion from task assignment and reward distribution.

| Property | Value |
|----------|-------|
| Epoch reward weight | 0× |
| Tasks assignable | None |
| Minimum duration | 7 days (score-based), 30 days (flag-based), permanent (core team decision) |
| Reinstatement | Formal appeal (see Section 4.3) |

### 3.3 Authorization Score Composition

The authorization score is a composite of four signals, each weighted. Initial weights shown below; governance can adjust per epoch.

| Signal | Weight | Source | Description |
|--------|--------|--------|-------------|
| Task alignment score | 40% | Verification pipeline | How aligned are completed tasks with the current roadmap |
| Completion quality | 25% | Reviewer scoring | Quality scores from task-specific verification |
| Behavioral consistency | 20% | Pattern analysis | Consistency of output over time; flags sudden quality drops or gaming patterns |
| Sybil risk | 15% | Sybil scoring pipeline | Inverse of sybil probability; high sybil risk reduces score |

Score range: 0.0 to 1.0. Thresholds: PROBATIONARY advancement ≥ 0.65, AUTHORIZED maintenance ≥ 0.45, TRUSTED advancement ≥ 0.75.

The score is computed on a rolling 30-day window. It is not a lifetime average — a contributor who was aligned 6 months ago but has drifted over the past month sees their current score reflect the drift.

### 3.4 Cooldown Mechanics

**UNKNOWN → PROBATIONARY**: 48-hour hold after first submission. Allows the network to flag obviously misaligned first completions before the contributor accumulates a task history.

**PROBATIONARY minimum duration**: 14 calendar days regardless of how quickly quantitative thresholds are met. Prevents gaming the threshold with burst low-effort completions.

**Authorization request rate limit**: One request per 30 days. Rejected requests do not restart the clock.

**Epoch weight ramp**: When a contributor advances from PROBATIONARY to AUTHORIZED, their epoch weight ramps from 0.25× to 1.0× over 7 days. This prevents day-one AUTHORIZED contributors from dominating epoch distributions in the first cycle after advancement.

**SUSPENDED reinstatement cooldown**: 7 days (score-based suspension), 30 days (manual flag), 90 days (repeated offense), permanent (core team explicit decision).

---

## 4. Escalation and Override Paths

### 4.1 Authorization Request (Standard Path)

When a PROBATIONARY contributor meets quantitative thresholds, they submit an authorization request containing:

1. **Identity disclosure**: Primary wallet address(es) and any associated wallets operated by the same entity
2. **Operational context**: What the contributor does, what infrastructure they run, intended scope
3. **Work samples**: Links to 3-5 completed tasks the contributor considers representative
4. **Alignment statement**: 200-500 words answering: "What does Post Fiat Network success look like in 12 months, and what role do you see yourself playing?"

Requests are submitted via a structured form (not a DM to the founder). In phase 1, this is a designated submission channel. In phase 2, it is an on-chain attestation.

### 4.2 Review Process

**Tier 1 — Automated pre-screening**: Authorization score, sybil score, and completion quality are checked against thresholds. Failed pre-screening returns the request with a specific deficiency notice — not a rejection.

**Tier 2 — Human review**: Core team adjudicates all requests in phase 1. SLA: 7 business days. Outcome: approve → AUTHORIZED, information request (14-day response window), or deny with written explanation.

**Tier 3 — TRUSTED council** (phase 2+): Standard PROBATIONARY requests are delegated to TRUSTED contributors operating via majority vote. Core team retains override and handles contested decisions. This is the path by which authorization becomes decentralized.

### 4.3 Suspension Appeal

A SUSPENDED contributor may appeal after the cooldown elapses by submitting:
1. Written acknowledgment of suspension reason
2. Specific remediation plan addressing the suspension cause
3. Supporting evidence where applicable

Approved appeals reinstate to PROBATIONARY (not prior state). The 14-day probationary minimum restarts.

### 4.4 Emergency Overrides

The core team retains authority to:
- **Fast-track**: Advance a contributor from UNKNOWN or PROBATIONARY to AUTHORIZED without completing standard thresholds (for known contributors or TRUSTED-sponsored entries)
- **Immediate suspend**: Remove any contributor from any state without prior notice when there is clear evidence of network harm
- **Weight override**: Temporarily adjust any contributor's epoch reward weight for any state

All overrides are logged with reason and operator identity.

---

## 5. Entry-Point Communication Gate

### 5.1 The Gap That Created kaiserlimp0

An operator who does not know that permissionless participation requires alignment with the roadmap — not just technically valid completions — cannot be held accountable for producing misaligned work at scale. The absence of a clear entry-point expectation is a system design failure, not a contributor failure.

### 5.2 Entry Acknowledgment Requirement

Before a wallet can be issued its first task, the Task Node requires completion of an entry acknowledgment. This is a lightweight structured action — not a legal agreement — that surfaces three facts:

1. **PFT is not mined freely**: Rewards are minted only for work that the network verifies as aligned with the current roadmap. Technical completion is necessary but not sufficient.
2. **Authorization is required for uncapped participation**: UNKNOWN contributors operate under weight caps. Uncapped participation requires advancing through the authorization process.
3. **Authorization requires engagement**: Specifically, submitting an authorization request that includes identity disclosure and an alignment statement. This is the explicit replacement for "contact the core team."

The acknowledgment is signed by the operator's wallet and logged. It cannot be skipped. It is approximately 200 words and should take under 3 minutes to read.

### 5.3 What This Changes

A future kaiserlimp0 who earns at high volume as a PROBATIONARY contributor is subject to the 0.25× epoch weight cap. They see, in the acknowledgment they signed, exactly why this cap exists and what they need to do to lift it. "I didn't know" is no longer a valid defense and, more importantly, it is no longer a reality for any new contributor.

---

## 6. Integration with Existing Verification and Scoring Pipeline

### 6.1 Pipeline Integration Points

```
Task Issuance ← [AUTHORIZATION GATE: pre-issuance check]
       ↓
Contributor Submission
       ↓
Verification
       ↓
Scoring ← [AUTHORIZATION GATE: post-completion score update]
       ↓
Epoch Reward Distribution ← [AUTHORIZATION GATE: weight application]
```

### 6.2 Pre-Issuance Authorization Check

Before any task is issued:
1. Look up contributor in authorization registry
2. Check current state and epoch reward weight
3. If SUSPENDED → block assignment
4. If UNKNOWN and task complexity exceeds UNKNOWN tier → block, assign lower-complexity task
5. If PROBATIONARY and rate limit exceeded → queue for next available window
6. If all checks pass → issue task

### 6.3 Post-Completion Score Update

After verification and scoring:
1. Record outcome in contributor's authorization history
2. Recompute rolling 30-day authorization score
3. Check demotion triggers (score < 0.45 for AUTHORIZED, score < 0.35 immediate flag for PROBATIONARY)
4. Update epoch reward weight based on current state
5. If PROBATIONARY and thresholds now met → flag as eligible to submit authorization request
6. Write updated record to authorization registry

### 6.4 Sybil Score Integration

The existing sybil scoring pipeline feeds into the authorization score (15% weight, Section 3.3) and gates authorization request advancement (Tier 1 pre-screening, Section 4.2). A contributor whose sybil score degrades after AUTHORIZED advancement triggers an automatic review flag.

### 6.5 Alignment Score Integration

The existing alignment scoring pipeline feeds into the authorization score (40% weight) and determines state transitions. Alignment score is not an input the contributor can game directly — it reflects whether completed work is semantically aligned with the current roadmap, as assessed by the verification system.

### 6.6 Authorization Registry Schema

| Field | Type | Description |
|-------|------|-------------|
| `wallet_address` | string | Primary wallet |
| `associated_wallets` | string[] | Disclosed additional wallets |
| `state` | enum | UNKNOWN / PROBATIONARY / AUTHORIZED / TRUSTED / SUSPENDED |
| `authorization_score` | float | Current composite score (0.0–1.0) |
| `epoch_weight` | float | Current epoch reward weight multiplier |
| `tasks_completed` | integer | Cumulative verified completions |
| `pft_epoch_share` | float | Current epoch accumulated share |
| `state_entered_at` | timestamp | When current state began |
| `entry_ack_signed_at` | timestamp | When entry acknowledgment was signed |
| `authorization_request_at` | timestamp | Last authorization request |
| `review_flags` | string[] | Active review flags |
| `suspension_reason` | string | If SUSPENDED, reason |
| `suspended_until` | timestamp | Earliest reinstatement date |

---

## 7. Rollout Plan

### Phase 1 — Bootstrap and Soft Gate (Weeks 1-4)
- Backfill all existing contributors into the registry
- Current Authorized DB members → AUTHORIZED state (no friction)
- Others → PROBATIONARY with credit for existing task history
- Entry acknowledgment required for all new registrations
- Authorization check runs in logging mode only — no tasks blocked
- Epoch emission mechanics designed but not yet enforced

### Phase 2 — Hard Gate (Weeks 5-8)
- Full enforcement of state-based task assignment restrictions
- Epoch reward weights applied in distribution
- Authorization request process live
- Core team adjudicating all PROBATIONARY requests

### Phase 3 — Council Delegation (Months 3-6)
- TRUSTED contributor pool large enough to form review council
- PROBATIONARY authorization delegated to council majority vote
- Core team retains override
- Epoch emission governance proposed to community

### Phase 4 — Algorithmic Authorization (Months 6-12)
- Authorization score is primary determinant of state (no manual toggle for standard cases)
- Manual toggle retained as emergency override only
- Score weights and epoch budget adjustments governed by TRUSTED council vote

---

## 8. Open Questions for Network Discussion

1. **What is the right epoch duration?** 28 days is proposed. Shorter epochs (14 days) are more responsive to contributor behavior but create more administrative overhead. Longer epochs (90 days) are more stable but slower to react to misalignment.

2. **What is the right base emission rate?** This requires the founding team's supply schedule targets. The framework can accommodate any base rate; the epoch multiplier does the adjusting.

3. **Who appoints the first TRUSTED contributors?** The founding team must seed the TRUSTED pool. What criteria and process govern these appointments?

4. **Cross-network identity credits**: Should verified contributors from adjacent networks (e.g., known ETH validators, contributors with track records in related protocols) receive a head start in authorization score? This could reduce friction for high-quality inbound contributors while maintaining the gate for unknown operators.

5. **What counts as "evidence" in a suspension appeal?** This needs a concrete list, not a vague standard, to prevent arbitrary adjudication.

---

## Appendix: Glossary

| Term | Definition |
|------|------------|
| Task Node | Network infrastructure that issues, tracks, and verifies task assignments |
| PFT | Post Fiat Token — the network's reward token, minted via verified task completion |
| Epoch | A fixed time window (proposed: 28 days) during which total PFT minted is bounded |
| Epoch budget | Total PFT authorized for minting in a given epoch |
| Authorization score | A composite per-contributor score (0.0–1.0) derived from task alignment, quality, behavioral consistency, and sybil risk |
| Epoch reward weight | A multiplier applied to a contributor's proportional share of the epoch budget, determined by authorization state |
| Authorization gate | The pre-task-issuance check that determines contributor eligibility and weight |
| TRUSTED council | A governance body of long-tenured contributors who adjudicate authorization requests and epoch governance proposals |
| Entry acknowledgment | A structured, wallet-signed statement confirming that the contributor understands the Proof of Alignment model |
| kaiserlimp0 | The pseudonym of the network's #2 all-time PFT earner, who operated without authorization — the existence proof that motivated this specification |

---

*This specification is intended as a starting point for network discussion and refinement. All thresholds, durations, and weights are proposals subject to adjustment based on network data and community feedback. Version 2.0 incorporates clarifications on emission mechanics, the definition of authorization, entry-point communication requirements, and the transition path from manual authorization to algorithmic reputation scoring.*
