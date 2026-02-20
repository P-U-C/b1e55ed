# Review Sprint Plan — Post-beta.2 Hardening

> Derived from three independent review panels:
> - **Review 1**: Mechanism design, event-sourcing, agent infra (Buterin, Moore, Floersch, Kleppmann, Young, Willison, Chase, Garg)
> - **Review 2**: Trading systems, quant validation (Hayes, Chitra, Hasu)
> - **Review 3**: Security audit, gaming vectors (Trail of Bits, samczsun)
>
> Priority: what must be true before real capital.

---

## Priority 0a: Critical Safety Fixes (Immediate)

**Problem**: The kill switch — the single most important safety mechanism — resets to SAFE on every process restart. Combined with auth timing attacks, these are exploitable in production today.

**Sprint FIX1: Safety Hotfix** *(< 1 day, block everything else)*
- [ ] **Kill switch persistence**: Read latest `KILL_SWITCH_V1` event from DB on `KillSwitch.__init__()` to restore level across restarts. Currently `self._level = KillSwitchLevel.SAFE` every time — meaning the 5-minute brain cron starts at L0 every cycle. *(Review 3: Trail of Bits, samczsun — P0)*
- [ ] **Timing-safe token comparison**: Replace `if token != expected:` (api/auth.py:39) with `hmac.compare_digest()`. *(Review 3: Trail of Bits — P1)*
- [ ] **Karma gates on paper mode**: `record_intent()` must check `execution.mode != "paper"` before creating intents. Paper PnL currently generates real karma obligations. *(Review 3: samczsun — P1)*
- [ ] **Karma default disabled**: Change `KarmaConfig.enabled = True` → `False`. Profit-sharing must never be default-on without explicit operator consent. README says "disabled" but code says `True`. *(Review 1: Buterin — P1)*
- [ ] **Signed genesis event**: First event's `prev_hash` is `None` — any event can claim to be genesis. Genesis must commit to node public key to prevent chain-splice attacks. *(Review 3: Trail of Bits — P1)*
- [ ] **Atomic batch append**: `append_events_batch` calls `append_event` in a loop with separate transactions. Crash mid-batch = partial chain. Wrap in single transaction. *(Review 2: Kleppmann — P1)*

---

## Priority 0b: Identity Unification (The Forge = The Identity)

**Problem**: Two identity systems — Ed25519 node identity + Ethereum Forge identity. Confusing, redundant, and the security boundary is unclear.

**Sprint U1: Unified Identity**
- [ ] Forge identity becomes the canonical identity (derive Ed25519 from Ethereum key, not separate)
- [ ] Remove dual-identity confusion: one key, one address, one node_id
- [ ] Key hierarchy: Forge Ethereum key → derive Ed25519 signing key → derive node_id
- [ ] Update `engine/security/identity.py` to derive from Forge key
- [ ] Update all references (events, karma, attestations) to use Forge address as canonical ID
- [ ] Migration path for existing identities

---

## Priority 1: Anti-Gaming + Proper Scoring (Before Real Value)

**Problem**: Reputation scoring is gameable via volume pumping, streak farming, hit-rate manipulation, selection bias.

**Sprint S1: Calibrated Scoring**
- [ ] Replace conviction 0-10 heuristic with proper scoring rules (Brier score or log score)
- [ ] Score on `profitable/submitted` not `profitable/accepted` (close selection bias)
- [ ] Replace streak with time-decayed contribution (penalize low-information drip)
- [ ] Add signal correlation/cloning detection (same signal repeated = penalized)
- [ ] Track and surface calibration curves per contributor

**Sprint S2: Anti-Spam + Sybil Resistance**
- [ ] Add submission quotas per contributor per time window
- [ ] Rate-limit signal ingestion per contributor_id
- [ ] Require minimum signal diversity (can't spam same asset/direction)
- [ ] Document: Forge is brand/culture layer, not Sybil brake
- [ ] Design admission criteria beyond Forge (stake/bond/invite for operator/agent roles)
- [ ] EAS revocation for proven bad signals ("reputation slashing")

---

## Priority 2: Karma Settlement Governance

**Problem**: Settlement policy is undefined — who can trigger, what prevents abuse, no multi-sig.

**Sprint K1: Settlement Rules**
- [ ] Define: karma computed per trade, per signal, or per contributor-weighted attribution
- [ ] Formalize settlement trigger rules (threshold, schedule, manual)
- [ ] Prevent operator from setting `karma_percentage` opportunistically (config immutability after first settlement)
- [ ] Prevent arbitrary `destination_wallet` changes (require attestation or multi-sig)
- [ ] Add settlement audit log (separate from karma_settlements — who triggered, when, why)
- [ ] Document settlement governance in `docs/karma-governance.md`

---

## Priority 3: Role Permissions (End-to-End)

**Problem**: Roles exist (operator, agent, tester, curator) but permissions aren't enforced per-command/endpoint/event.

**Sprint P1: Permission Model**
- [ ] Define permission matrix: which commands/endpoints per role
- [ ] Define: which event types can be emitted by which roles
- [ ] Implement role-based access control on API endpoints
- [ ] Implement role-based CLI gating
- [ ] Escalation path: kill switch levels map to role restrictions
- [ ] Document in `docs/permissions.md`

| Role | Can Signal | Can Brain | Can Kill Switch | Can Settle Karma | Can Register Producers |
|------|-----------|-----------|-----------------|-----------------|----------------------|
| operator | ✅ | ✅ | ✅ | ✅ | ✅ |
| agent | ✅ | ❌ | ❌ | ❌ | ✅ (own only) |
| curator | ✅ | ❌ | ❌ | ❌ | ❌ |
| tester | ✅ (limited) | ❌ | ❌ | ❌ | ❌ |

---

## Priority 4: Event Replay + Projection Integrity

**Problem**: Projections (positions, regime, leaderboard) must be rebuildable from events alone. No replay tooling exists.

**Sprint R1: Replay Infrastructure**
- [ ] `b1e55ed replay [--from EVENT_ID] [--to EVENT_ID]` — rebuild all projections from events
- [ ] Verify: positions, regime, leaderboard, contributor scores all rebuildable without external state
- [ ] Add invariant test: replay from genesis produces identical projection state
- [ ] Schema versioning: implement upcaster/migration for payload schemas (schema_version exists but no replay tooling)
- [ ] Event schema registry: typed events per brain phase (`ConvictionUpdated`, `RegimeChanged`, etc.)
- [ ] Hash-chain compaction/snapshotting strategy for long-lived chains

---

## Priority 5: Concurrency + Authority Model

**Problem**: Single-node SQLite is fine for v1, but authority rules are implicit. Two processes can fork the hash chain via cached `_last_hash`.

**Sprint A1: Authority Documentation + Enforcement**
- [ ] Document: "one brain writer" rule explicitly
- [ ] Document: producer trust boundaries (authenticated registration, but what about poisoned signals?)
- [ ] Enforce: WAL mode + write lock already exist — add explicit concurrency tests
- [ ] Document: fork detection if operator runs multiple instances
- [ ] Add `b1e55ed integrity check` CLI command (verify hash chain, detect forks)
- [ ] Add SQLite write-lock enforcement: detect concurrent writers and fail-fast rather than silently fork *(Review 2: Kleppmann — P1)*
- [ ] `_last_hash` must be read inside the transaction, not cached across calls *(Review 2: Kleppmann)*

---

## Priority 6: Producer Hardening

**Problem**: Dynamic producer registration is powerful but is a security boundary.

**Sprint PH1: Producer Security**
- [ ] Authenticated registration with role-based controls
- [ ] Sandboxing: timeouts on producer endpoint polling
- [ ] Input validation: schema enforcement on producer signal responses
- [ ] SSRF protection: allowlist/denylist for producer endpoint URLs
- [ ] Rate limiting per producer
- [ ] Health degradation: auto-deregister after N consecutive failures
- [ ] Poisoning detection: statistical anomaly detection on producer outputs

---

## Priority 7: Crypto Primitive Unification

**Problem**: FORGE_SPEC says AES-256-GCM + Argon2id; security doc shows PBKDF2-HMAC-SHA256. Mismatch.

**Sprint C1: Crypto Unification**
- [ ] Audit all encryption paths in codebase
- [ ] Pick one KDF (Argon2id) and one cipher (AES-256-GCM)
- [ ] Update all code paths to use unified primitives
- [ ] Update all docs to match
- [ ] Add property-based tests proving encryption roundtrips
- [ ] Key rotation story: what happens to reputation/karma if keys rotate
- [ ] Document threat model (local compromise, backup compromise, supply chain)

---

## Priority 8: Backtest + Validation Rigor

**Problem**: Backtest engine is entirely empty — all files are placeholders. No strategy validation exists. A trading system without backtesting is an opinion with leverage.

**Sprint B1: Quant Validation** *(Review 3: Tarun Chitra — P0)*
- [ ] **Implement backtest engine** — `engine/backtest/engine.py`, `simulator.py`, `sweep.py`, `validation.py` are all `"""Module placeholder."""`. Zero implementation.
- [ ] **Implement strategies** — 9 strategy files (breakout, combined, funding_arb, ma_crossover, mean_reversion, momentum, rsi_reversion, trend_following, volatility) are all placeholders
- [ ] Historical data replay through brain pipeline against price/signal data
- [ ] Surface backtest engine in public docs (currently only in tests/)
- [ ] Formalize walk-forward spec with embargo periods
- [ ] Explicit leak prevention between training and evaluation sets
- [ ] Multiple-hypothesis correction (FDR) on signal/strategy mining — document methodology
- [ ] Adversarial assumptions for on-chain signals ("what if a whale wants me to see this flow?")
- [ ] Regime-conditioned backtests: validate regime detector independently, then test strategies per-regime
- [ ] **Dynamic Kelly**: Replace static `p=0.55, b=1.2` with feedback from realized performance. Static Kelly is worse than useless across regime transitions. *(Review 3: Chitra — P2)*

---

## Priority 9: External Auditability

**Problem**: Hash chain is locally verifiable but not externally anchored.

**Sprint E1: External Verification**
- [ ] Periodic hash-chain root posting on-chain (Ethereum or L2)
- [ ] `b1e55ed anchor` CLI command — post current root to EAS or contract
- [ ] Make EAS verification a portable proof workflow (verifier can check without trusting operator)
- [ ] Expose EAS UID of each contributor in REST `/contributors` endpoint

---

## Priority 10: Agent Infrastructure Gaps

**Problem**: "Agent-first" system lacks agent-native interfaces. REST-only is insufficient for AI operator use case.

**Sprint AG1: Agent Interfaces** *(Review 3: Willison, Chase, Garg — P2)*
- [ ] **MCP (Model Context Protocol) server**: Let LLM agents interact with b1e55ed as a native tool — no HTTP semantics required
- [ ] **SSE/WebSocket event stream**: Push-based event delivery for real-time agent consumption. Webhooks are fire-and-forget, not a subscription protocol
- [ ] **Signal attribution projection**: Single `signal_id → trade_outcome` view. Currently requires manual join across `contributor_signals → conviction_log → positions`
- [ ] **Producer feedback channel**: Brain should tell producers "your last N signals were wrong, recalibrate." Learning loop adjusts domain weights but individual producers get no feedback
- [ ] **Stateful session management**: Agent running multi-step strategy (analyze → decide → execute → monitor) needs context across API calls. Extend `trace_id` for operator-initiated trace chains
- [ ] **Producer self-service**: New agent can't introspect "what signal types can I emit?" or "what schema does the brain expect?" Add capability discovery endpoint

**Sprint AG2: CLI Decomposition** *(Review 3: Willison — P2)*
- [ ] Split `engine/cli.py` (60KB monolith) into Click/Typer command groups — one file per command group
- [ ] Reduces merge conflicts, improves testability

---

## Priority 11: Signal Quality + Normalization

**Problem**: On-chain signals use absolute values without market-cap normalization. Same number means different things for BTC vs SUI.

**Sprint SQ1: Signal Normalization** *(Review 3: Hasu — P2)*
- [ ] Normalize `whale_netflow` to market cap or daily volume (current: `0.5 + netflow / 200.0` — arbitrary scale)
- [ ] Normalize `exchange_flow` similarly
- [ ] Add MEV-aware signal: builder/searcher activity, sandwich volume, toxic flow concentration
- [ ] All 13 producers need real data sources — currently structural shells with no data fetching *(Review 3: Hayes — P0)*

---

## Priority 12: Production Security Hardening

**Problem**: Dev-mode escape hatches and key handling patterns that are fine for beta but must not ship to production.

**Sprint SEC1: Hardening** *(Review 3: Trail of Bits — P1/P2)*
- [ ] **Remove plaintext key fallback in production**: `identity.py` lines 101-112 allow unencrypted private key save when `B1E55ED_DEV_MODE=1`. In production builds, remove this code path entirely — don't just gate it
- [ ] **Private key memory safety**: `NodeIdentity` stores private key as hex string on Python heap — visible in core dumps/swap. Consider `mlock()`/`mprotect()` via ctypes, or zero key material after use
- [ ] **Separate kill switch auth**: `POST /brain/kill-switch` uses same auth token as regular API. Compromised token = can reset the safety mechanism. Kill switch should require elevated auth
- [ ] **API rate limiting**: No rate limiting on signal ingestion. Compromised token → flood curator endpoint → poison synthesis
- [ ] **TLS enforcement**: Docker setup exposes ports 5050/5051 on container network. Document TLS requirement for non-localhost deployments
- [ ] **Hash chain fast verification gap**: `fast=True` mode trusts first row's `prev_hash`. Truncation attack (delete middle events, re-chain remainder) passes fast verify. Add periodic full verification or signed checkpoints
- [ ] **Event ordering**: `ORDER BY created_at ASC, rowid ASC` — same-timestamp events depend on rowid ordering which is implementation-dependent across SQLite versions. Use monotonic sequence number

---

## Execution Order

| Phase | Sprints | Gate |
|-------|---------|------|
| **Immediate (block all else)** | FIX1 | Kill switch, auth, karma defaults |
| **Before real capital** | U1, S1, S2, K1, P1, C1 | Must complete |
| **Before >$10K AUM** | R1, A1, PH1, B1, SEC1 | Should complete |
| **Before >$100K AUM** | E1, AG1, AG2, SQ1, formal audit | Required |

---

## The Top 15 (Three-Panel Consensus)

1. **Kill switch persistence across restarts** *(NEW — P0)*
2. Replace score heuristics with calibrated scoring + anti-spam costs
3. **Timing-safe auth + karma paper-mode gate** *(NEW — P1)*
4. Formalize acceptance criteria and prevent selection bias
5. Define karma settlement governance (who, how, cryptographic checks)
6. Clarify role permissions end-to-end (CLI/API/events)
7. **Backtest engine implementation (currently empty)** *(ELEVATED — P0)*
8. Make replay/rebuild a first-class invariant for projections
9. Document concurrency/authority model (single brain writer, producer trust)
10. Unify crypto primitives across docs + code and add tests
11. Producer registration hardening (authz, validation, SSRF/timeout)
12. Unify Forge identity with security identity (one key, one address)
13. **MCP interface + streaming events for agents** *(NEW — P2)*
14. **Signal normalization to asset scale** *(NEW — P2)*
15. Make EAS verification a verifier workflow (portable proofs)

---

---

## Review 3 Finding Cross-Reference

All Review 3 findings mapped to sprints:

| Finding | Severity | Sprint | Status |
|---------|----------|--------|--------|
| Kill switch resets on restart | P0 | **FIX1** | Added |
| Backtest engine empty | P0 | **B1** (elevated) | Updated |
| All 13 producers are stubs | P0 | **SQ1** | Added |
| Signed genesis event | P1 | **FIX1** | Added |
| Karma defaults to enabled | P1 | **FIX1** | Added |
| Paper trades → karma intents | P1 | **FIX1** | Added |
| SQLite concurrent write hazard | P1 | **A1** | Updated |
| Timing attack on token comparison | P1 | **FIX1** | Added |
| Scoring gaming (volume/streak) | P1 | S1/S2 | Already covered |
| Hit rate denominator problem | P1 | **S1** | Already covered |
| Projections not event-derived | P2 | R1 | Already covered |
| No event compaction | P2 | R1 | Already covered |
| Static Kelly parameters | P2 | **B1** | Added |
| On-chain signal normalization | P2 | **SQ1** | Added |
| No MCP interface | P2 | **AG1** | Added |
| CLI 60KB monolith | P2 | **AG2** | Added |
| No streaming events | P2 | **AG1** | Added |
| No producer feedback channel | P2 | **AG1** | Added |
| Batch append not atomic | P1 | **FIX1** | Added |
| Dev-mode plaintext key path | P2 | **SEC1** | Added |
| Private key memory safety | P2 | **SEC1** | Added |
| Kill switch shared auth | P2 | **SEC1** | Added |
| No API rate limiting | P2 | **SEC1** | Added |
| Hash chain fast-verify gap | P2 | **SEC1** | Added |
| Event ordering rowid dependency | P2 | **SEC1** | Added |
| EAS attestation is stub | P3 | E1 | Already covered |
| Forge not wired into engine | P3 | U1 | Already covered |
| No event versioning/upcasters | P2 | R1 | Already covered |

---

*"This is not just another trading bot — it's a self-improving, auditable, agent-governed intelligence layer."*
*— The Review Panel*

*Last updated: 2026-02-20 — Integrated Reviews 1, 2, and 3*
