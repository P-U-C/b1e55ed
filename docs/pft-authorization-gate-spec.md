# Post Fiat Network: Task Authorization Gate Specification

**Version:** 1.0.0  
**Date:** 2026-03-14  
**Status:** Proposed  
**Author:** b1e55ed (Oracle Node Operator, Synthesis Hackathon Participant)

---

## Executive Summary

The Post Fiat Network's #2 all-time PFT earner operated for an extended period without ever contacting the core team, accumulating nearly 1,000,000 PFT before the gap was identified. This is not a bug — it is a feature of a permissionless network working exactly as designed. But permissionless onboarding creates a governance vacuum: the network cannot distinguish between a well-aligned, high-quality contributor and an adversarial agent optimizing for reward extraction without producing genuine value.

This specification defines a **Task Authorization Gate**: a state machine that governs contributor access to the task assignment pipeline, with progressive trust escalation, earning caps by authorization tier, cooldown mechanics for unknown operators, and integration points with the existing sybil and alignment scoring infrastructure. The goal is not to prevent participation — it is to create structured accountability that converts unknown operators into verified, trusted contributors through demonstrated behavior.

---

## 1. Problem Statement

### 1.1 The Authorization Gap

The current Task Node verification pipeline validates individual task completions but has no contributor-level authorization layer. Any wallet can:

1. Register as a Task Node operator
2. Begin receiving task assignments
3. Submit completions and accumulate PFT rewards

This pipeline is correct for permissionless networks at early stages. However, as the network matures and PFT rewards become economically significant, the absence of contributor-level authorization creates several failure modes:

- **Misaligned operators**: Agents optimizing for reward extraction produce technically valid completions that are semantically hollow or misaligned with network goals
- **Sybil accumulation**: Multiple wallets operated by a single entity can accumulate disproportionate rewards without disclosure
- **No accountability path**: When a contributor produces poor or misaligned work, there is no established mechanism to restrict their access short of hard blacklisting
- **Core team information asymmetry**: The team cannot identify high-value operators proactively or establish relationships that improve task quality

### 1.2 Design Constraints

The authorization gate must satisfy four constraints:

1. **Non-disruptive to existing authorized operators**: Anyone currently in good standing should transition to Authorized state without friction
2. **Progressive, not punitive**: The gate creates opportunity for legitimate contributors to earn trust, not a wall that permanently excludes them
3. **Decentralization-compatible**: Authorization decisions must eventually be delegable to the network, not permanently centralized on the core team
4. **Auditable**: All state transitions must be logged on-chain or in a verifiable off-chain store

---

## 2. Contributor State Machine

### 2.1 State Definitions

The authorization gate defines **four contributor states**:

```
UNKNOWN → PROBATIONARY → AUTHORIZED → TRUSTED
                ↓
           SUSPENDED (from any state)
```

#### State 0: UNKNOWN
The default state for any wallet that has registered as a Task Node operator but has no prior interaction history with the network.

| Property | Value |
|----------|-------|
| PFT earning cap | 500 PFT/week |
| Task assignment rate | 1 task per 48 hours |
| Task types available | Low-complexity, low-reward only |
| Cooldown trigger | Automatic on first task submission |

An UNKNOWN contributor is automatically placed in PROBATIONARY state upon first task submission. The 500 PFT/week cap and 48-hour task rate are enforced by the Task Node assignment layer before any task is issued.

#### State 1: PROBATIONARY
A contributor who has submitted at least one task completion but has not yet been reviewed or verified. This is the active evaluation period.

| Property | Value |
|----------|-------|
| PFT earning cap | 5,000 PFT/week |
| Task assignment rate | Up to 3 tasks per 24 hours |
| Task types available | Standard complexity, standard reward |
| Minimum duration | 14 calendar days |
| Advancement trigger | 10 completed tasks + alignment score ≥ 0.65 + explicit authorization request |

A PROBATIONARY contributor remains capped regardless of output volume. They cannot graduate to AUTHORIZED automatically — the transition requires both a quantitative threshold and an explicit human-in-the-loop authorization request (see Section 3).

#### State 2: AUTHORIZED
A contributor who has passed the probationary review and received explicit authorization from the core team or a delegated council.

| Property | Value |
|----------|-------|
| PFT earning cap | None (uncapped) |
| Task assignment rate | No rate limit |
| Task types available | All, including high-reward strategic tasks |
| Minimum duration | Indefinite |
| Demotion trigger | Alignment score < 0.45 for 30 consecutive days OR explicit revocation |

AUTHORIZED is the operational state for all existing productive contributors. Operators currently in good standing are backfilled into this state at gate launch.

#### State 3: TRUSTED
A long-tenured AUTHORIZED contributor with a verified track record. TRUSTED operators gain access to governance participation and can adjudicate authorization requests from PROBATIONARY contributors.

| Property | Value |
|----------|-------|
| All AUTHORIZED privileges | Inherited |
| Governance participation | Yes — can vote on authorization requests |
| Delegation authority | Can sponsor PROBATIONARY contributors |
| Advancement trigger | 90 days AUTHORIZED + alignment score ≥ 0.75 + ≥ 500 PFT earned + nomination by existing TRUSTED member |

#### State: SUSPENDED
Any contributor can be moved to SUSPENDED from any state. SUSPENDED operators receive zero task assignments and cannot earn PFT. Suspension is always time-bounded unless explicitly marked permanent.

| Property | Value |
|----------|-------|
| PFT earning cap | 0 |
| Task assignment rate | 0 |
| Minimum duration | 7 days (temporary) |
| Maximum duration | Permanent (requires explicit core team decision) |
| Reinstatement path | Formal appeal to core team (see Section 3.3) |

### 2.2 State Transition Triggers

| From | To | Trigger | Who Initiates |
|------|----|---------|---------------|
| UNKNOWN | PROBATIONARY | First task submission | Automatic |
| PROBATIONARY | AUTHORIZED | 10 tasks + score ≥ 0.65 + authorization request reviewed | Core team / TRUSTED council |
| PROBATIONARY | SUSPENDED | Score < 0.35 sustained OR explicit flag | Core team |
| AUTHORIZED | TRUSTED | 90 days + score ≥ 0.75 + 500 PFT + nomination | TRUSTED council vote |
| AUTHORIZED | SUSPENDED | Score < 0.45 for 30 days OR explicit revocation | Core team |
| TRUSTED | SUSPENDED | Explicit revocation | Core team only |
| SUSPENDED | PROBATIONARY | Successful appeal + cooldown elapsed | Core team |

### 2.3 Cooldown Mechanics

Cooldowns prevent rapid cycling between states and rate-limit the authorization overhead imposed on the core team.

**UNKNOWN → PROBATIONARY cooldown**: 48 hours after first submission before any additional tasks are assigned. This is a mandatory hold that allows the network to flag obviously misaligned first submissions before the contributor accumulates more work.

**PROBATIONARY minimum duration**: 14 calendar days, regardless of how quickly the quantitative thresholds are met. A contributor who completes 10 tasks in 3 days still waits 11 more days before the authorization request can be submitted. This prevents gaming the threshold with low-effort completions.

**SUSPENDED reinstatement cooldown**: 7 days minimum. For contributors suspended for alignment reasons (score-based), the cooldown extends to 30 days. For contributors suspended for explicit flags (manual revocation), the cooldown extends to 90 days.

**Authorization request rate limit**: A PROBATIONARY contributor can submit one authorization request per 30-day period. Rejected requests do not restart the 30-day clock.

**PFT threshold trigger**: If a PROBATIONARY contributor earns > 3,000 PFT in a single week (approaching the 5,000/week cap), an automatic review flag is raised with the core team. This catches high-velocity contributors who may be approaching the cap and either deserve fast-track authorization or warrant closer inspection.

---

## 3. Escalation and Override Paths

### 3.1 Standard Authorization Request

When a PROBATIONARY contributor meets the quantitative thresholds (10 tasks, alignment score ≥ 0.65, 14 days elapsed), they become eligible to submit an authorization request. The request must include:

1. **Identity disclosure**: Wallet address(es) used to participate in the network. Declaration of any additional wallets associated with the same operator.
2. **Operational context**: Brief description of what the contributor does, what tools/infrastructure they operate, and their intended scope of participation.
3. **Work sample**: Links to 3-5 completed tasks the contributor considers representative of their best work.
4. **Alignment statement**: A short written response (200-500 words) to the question: "What does Post Fiat Network success look like in 12 months, and what role do you see yourself playing in it?"

Requests are submitted via a designated channel (initially: direct message to core team; future state: on-chain attestation to a designated contract address).

### 3.2 Review and Adjudication

**Tier 1 — Automated pre-screening**: The request is automatically scored against:
- Alignment score trajectory (is it trending up or down over the probationary period?)
- Task completion quality scores (are completions flagged as low-effort or off-topic?)
- Sybil score (does the wallet show patterns consistent with coordinated multi-wallet operation?)

If all three pass basic thresholds, the request advances to human review. If any fail, the request is automatically returned with a specific deficiency notice.

**Tier 2 — Human review**: In the initial phase, the core team adjudicates all authorization requests. Review SLA: 7 business days from receipt of a complete request. The reviewer reads the alignment statement, spot-checks 2-3 task completions, and either: (a) approves and transitions the contributor to AUTHORIZED, (b) requests additional information with a 14-day response window, or (c) denies with a written explanation.

**Tier 3 — TRUSTED council review** (future state): As the TRUSTED contributor tier grows, authorization decisions for standard PROBATIONARY requests can be delegated to a TRUSTED council operating via simple majority vote (e.g., 3-of-5 TRUSTED members). The core team retains override authority and handles contested decisions.

### 3.3 Suspension Appeal

A SUSPENDED contributor may appeal their suspension by submitting:

1. **Acknowledgment**: Written acknowledgment of the reason for suspension
2. **Remediation plan**: Specific, concrete changes to their operation that address the suspension reason
3. **Evidence**: If the suspension was score-based, evidence that the underlying issue has been addressed (e.g., improved task quality in a different context, external references)

Appeals are reviewed by the core team with a 14-day SLA. Approval reinstates the contributor to PROBATIONARY state (not their previous state), with the standard 14-day probationary minimum restarting from the reinstatement date.

### 3.4 Emergency Override

The core team retains authority to:
- **Fast-track authorization**: Move a contributor directly from UNKNOWN or PROBATIONARY to AUTHORIZED without completing standard thresholds. Used for known contributors from other networks or contributors introduced by TRUSTED operators.
- **Immediate suspension**: Suspend any contributor from any state without prior notice when there is clear evidence of network harm (e.g., coordinated sybil attack, submission of fabricated completions).
- **Cap override**: Temporarily raise or lower the PFT earning cap for any contributor in any state.

All emergency overrides are logged with a reason and the identity of the core team member who initiated them.

---

## 4. Integration with Task Node Verification and Scoring Pipeline

### 4.1 Pipeline Architecture

The existing Task Node verification pipeline operates in the following sequence:

```
Task Issuance → Contributor Submission → Verification → Scoring → Reward Distribution
```

The authorization gate inserts at **Task Issuance** (pre-submission gate) and **Scoring** (post-completion state update).

### 4.2 Pre-Submission Gate (Task Issuance Integration)

Before any task is issued to a contributor, the Task Node performs an authorization check:

```
AUTHORIZATION CHECK:
  1. Look up contributor wallet in authorization registry
  2. Determine current state: UNKNOWN / PROBATIONARY / AUTHORIZED / TRUSTED / SUSPENDED
  3. Check current-week PFT earned against state cap
  4. Check task rate against state rate limit
  5. IF SUSPENDED → reject assignment, no task issued
  6. IF cap exceeded → reject assignment, queue task for post-reset issuance
  7. IF all checks pass → issue task normally
```

The authorization registry is a lightweight key-value store (wallet address → authorization state record). In the initial implementation this is an off-chain database maintained by the network; in a future decentralized implementation it is an on-chain mapping.

### 4.3 Post-Completion State Update (Scoring Integration)

After a task completion is verified and scored, the scoring pipeline feeds back into the authorization gate:

```
SCORING INTEGRATION:
  1. Record completion outcome in contributor's authorization history
  2. Recompute rolling alignment score (7-day and 30-day windows)
  3. Check demotion triggers:
     a. AUTHORIZED contributors: flag if 30-day alignment score < 0.45
     b. PROBATIONARY contributors: check if 10-task threshold now met
  4. Increment weekly PFT earned counter
  5. Check PFT threshold trigger: if PROBATIONARY and weekly PFT > 3,000 → raise review flag
  6. Write updated state record to authorization registry
```

### 4.4 Sybil Score Integration

The existing sybil scoring pipeline produces a per-wallet sybil score. The authorization gate consumes this score at two points:

- **Authorization request pre-screening** (Section 3.2, Tier 1): Sybil score below the threshold causes automatic request rejection pending identity disclosure review
- **Ongoing monitoring**: AUTHORIZED and TRUSTED contributors whose sybil scores degrade significantly over time (e.g., new wallets appearing with correlated behavior) trigger an automatic review flag

### 4.5 Alignment Score Integration

The alignment scoring pipeline produces a per-contributor alignment score that reflects how well the contributor's task outputs align with network goals. The authorization gate consumes this score at multiple points:

- **PROBATIONARY advancement threshold**: Score ≥ 0.65 required to submit authorization request
- **AUTHORIZED demotion trigger**: Score < 0.45 sustained for 30 days triggers review
- **TRUSTED advancement threshold**: Score ≥ 0.75 required
- **Suspension appeal**: Score trajectory is a primary input to appeal adjudication

### 4.6 Authorization Registry Schema

Each entry in the authorization registry contains:

| Field | Type | Description |
|-------|------|-------------|
| `wallet_address` | string | Primary wallet (hex) |
| `associated_wallets` | string[] | Disclosed additional wallets |
| `state` | enum | UNKNOWN / PROBATIONARY / AUTHORIZED / TRUSTED / SUSPENDED |
| `state_entered_at` | timestamp | When current state began |
| `tasks_completed` | integer | Cumulative completed tasks |
| `pft_earned_week` | float | PFT earned in current calendar week |
| `pft_earned_total` | float | Lifetime PFT earned |
| `alignment_score_7d` | float | 7-day rolling alignment score |
| `alignment_score_30d` | float | 30-day rolling alignment score |
| `authorization_request_at` | timestamp | Last authorization request submitted |
| `review_flags` | string[] | Active review flags |
| `suspension_reason` | string | If SUSPENDED, reason for suspension |
| `suspended_until` | timestamp | Earliest reinstatement date |

---

## 5. Rollout Plan

### Phase 1 — Registry Bootstrap (Week 1-2)
Backfill all existing contributors into the registry. Any contributor with ≥ 10 tasks completed and alignment score ≥ 0.65 is initialized as AUTHORIZED. All others are initialized as PROBATIONARY with credit for tasks already completed.

### Phase 2 — Soft Gate (Weeks 3-4)
The authorization check runs but only logs — no tasks are blocked. This surfaces edge cases and allows the team to audit the gate logic before enforcement.

### Phase 3 — Hard Gate (Week 5+)
Full enforcement: task issuance blocked for SUSPENDED contributors and cap/rate limits enforced for UNKNOWN and PROBATIONARY contributors.

---

## 6. Open Questions

1. **What is the right PROBATIONARY earning cap?** 5,000 PFT/week is a proposal. The right number depends on average task rewards — it should be low enough to be a meaningful constraint but high enough that a legitimate contributor can produce real signal during probation.

2. **Who constitutes the initial TRUSTED council?** The first TRUSTED contributors need to be appointed by the core team. What criteria and process govern this?

3. **On-chain vs. off-chain registry?** An off-chain registry is faster to ship but creates a centralization dependency. An on-chain mapping is more decentralized but adds gas costs and deployment complexity.

4. **Cross-network identity**: Contributors who are known in other networks (e.g., verified Anthropic Claude users, verified ETH validators) should they receive credit toward authorization via a fast-track path?

---

## Appendix: Glossary

| Term | Definition |
|------|------------|
| Task Node | The network infrastructure component that issues, tracks, and verifies task assignments |
| PFT | Post Fiat Token — the network's reward token |
| Alignment Score | A per-contributor score reflecting the semantic alignment of task completions with network goals |
| Sybil Score | A per-wallet score reflecting the probability that the wallet is part of a coordinated multi-wallet operation |
| Authorization Gate | The pre-task-issuance check that determines whether a contributor is eligible to receive a task assignment |
| TRUSTED Council | A future governance body composed of long-tenured TRUSTED contributors who can adjudicate authorization requests |

---

*This specification is intended as a starting point for community discussion and refinement. All thresholds and durations are proposals subject to revision based on network data and community feedback.*
