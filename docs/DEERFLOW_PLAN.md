# DeerFlow × b1e55ed — Integration Plan (v3)

> **Status:** Planning — 2026-03-07 (revised after external DeerFlow-perspective review)
> **Analysis:** Opus 4.6 dual-session + external review against DeerFlow 2.0 actual architecture
> **Branch strategy:** `feat/deerflow` → `develop`

---

## Framing

b1e55ed is harness-agnostic. Two harnesses. Different institutional roles.

```
                         b1e55ed
              (events · brain · karma · MCP · flywheel)
                              │
              ┌───────────────┴───────────────┐
              │                               │
           OpenClaw                       DeerFlow
     Personal Operator Layer          Institutional Research Desk
     ──────────────────────          ─────────────────────────────
     Individual trader               Analysts, funds, research teams
     Real-time, reactive             Autonomous, systematic
     Conversational                  Long-running (minutes→hours)
     High trust, direct control      Artifact-producing
     "What do I do right now?"       "Cover 30 tokens, IC brief by 7AM"
```

No retail layer. That's a separate product with regulatory implications b1e55ed isn't positioned for. If retail emerges, it's a third-party wrapper on the Oracle API.

---

## Target Customer

3-10 person crypto fund, $50-200M AUM, conviction-based strategy, no dedicated quant team. They have capital and edge but are drowning in information. DeerFlow gives them research throughput. b1e55ed gives them systematic synthesis and a hash-chained audit trail.

Secondary: Crypto-native research shops (Delphi-tier) running content production pipelines where signal provenance matters.

---

## What DeerFlow Opens Up

**Systematic token coverage at scale.** A 3-person fund can't research 30 tokens manually. DeerFlow's coordinator decomposes a research task, executes sub-steps sequentially or in parallel via its planner, synthesizes into a ranked conviction output. Research throughput of an 8-person team, automated.

**IC-ready artifacts.** Regime overview + top signals + position rationale + risk summary → HTML brief or PDF. Scheduled. Shareable. Timestamped. Tied to b1e55ed's hash chain.

**Persistent research memory.** DeerFlow 2.0 has long-term memory across sessions. A 6h research cycle remembers what it found last cycle — regime shifts, conviction changes, prior signals. Research evolves rather than restarting cold.

**LP/investor reporting.** Quarterly performance attribution, strategy narrative, forward outlook — grounded in b1e55ed's hash-chained event history. Audit-defensible by construction.

**Sandboxed quant execution.** Backtest runs via DeerFlow sandbox (isolated Python environment). Pulls data via MCP, executes script, returns formatted artifact. b1e55ed's backtest engine does the heavy lifting; DeerFlow wraps it in natural language.

**Local model support for compliance.** TradFi desks need on-premise models. DeerFlow supports local models. b1e55ed's MCP server is model-agnostic. Together: fully self-hostable institutional intelligence stack.

---

## Critical Architecture Decisions

### How DeerFlow Actually Uses MCP Tools

**Important correction from v2:** DeerFlow does NOT auto-discover MCP tools and use them autonomously at runtime. Tool selection is driven by the `extensions_config.json` registration and — more importantly — by the **skill file itself**. The SKILL.md file tells the coordinator which tools to call and in what order. The coordinator doesn't scan tool descriptions and decide; it follows the skill's structured workflow.

**Implication:** S0's "rewrite MCP tool descriptions for LLM discoverability" is misplaced effort. The descriptions matter for human understanding, not for DeerFlow's planner. Put the writing effort into the SKILL.md files — that's what actually controls tool usage.

### How Sub-Agent Orchestration Works

**Important correction from v2:** DeerFlow's sub-agent system works through the coordinator's task decomposition — you define the research goal and the planner breaks it into steps. You don't imperatively "spawn named sub-agents for specific data domains." The skill file describes the workflow as a structured plan; the coordinator decomposes and executes.

**Implication:** Skill files must be written as structured research plans, not as imperative sub-agent assignments. Read DeerFlow's existing `skills/public/` skill files before writing ours — they follow a specific structure the coordinator parses.

### Composable MCP Tools — Not a Monolith

**`get_narrator_context` (pre-packaged context block) is an anti-pattern.** DeerFlow's coordinator is designed to compose context from multiple tool calls. A monolithic context block prevents adaptation: the brief skill needs positions, the thesis skill needs signals, the backtest skill needs neither.

**Replace with three composable tools:**
- `get_regime_status` — current regime + kill switch level
- `get_top_signals` — recent signals, domain-filtered, paginated
- `get_open_positions` — live book with P&L

Let the coordinator call what it needs for each task.

### Sub-Agent → Producer: Aggregator Pattern

One DeerFlow task = one b1e55ed event. The aggregator pattern.

```
DeerFlow Skill: "Research $TOKEN"
    Coordinator decomposes into steps:
    ├── Step: gather on-chain data (MCP: get_top_signals domain=onchain)
    ├── Step: web search social/CT sentiment
    ├── Step: tokenomics/narrative review
    └── Step: synthesize → ResearchSignalPayload
                     │
                     ▼
      signal.research.v1 → b1e55ed (one event)
      Artifact file → sandbox filesystem
                     │
                     ▼
      deerflow_research.py picks up artifact,
      hashes it, stores it, triggers distribution
```

Sub-agent internals are DeerFlow's problem. b1e55ed sees the synthesized output only. The `sources[]` array provides provenance without polluting the event stream.

### Signal Trust — Schema-Enforced Taxonomy

Signal class taxonomy enforced at the **payload schema level**, not the honor system.

| Class | Schema Requirement | Brain Weight | Use |
|-------|--------------------|-------------|-----|
| `observation` | No directional claim allowed | Low | DeerFlow research findings, social scans |
| `detection` | Event timestamp required | Medium | On-chain events, price alerts |
| `conviction` | Falsifiable prediction + time horizon required | High | Scored thesis, validated call |

`submit_research_signal` validates class at ingestion time. A DeerFlow synthesis that makes a directional claim must declare itself `conviction` and provide a horizon — or it's rejected.

**Volume-dampened karma — per token, not per producer.** Frequency penalty is per (producer, symbol) pair. A watchlist skill covering 30 tokens is treated as 30 independent signal sources, not one high-frequency producer. Prevents the perverse incentive of splitting one watchlist skill into 30 separate skills.

**LLM karma ceiling.** DeerFlow-sourced signals have a hard karma cap until validated by outcomes. Rises automatically as outcome validation accumulates.

### Identity and Attribution

When DeerFlow emits a signal into b1e55ed, karma flows to the **human operator who configured and deployed the skill** — their forge node ID.

- `submit_research_signal` requires a signed `operator_node_id` field (not optional)
- DeerFlow doesn't have its own identity system; the operator is the accountable party
- This preserves flywheel integrity: human judgment → outcome → karma → weight

### Multi-Tenancy — Harness-Agnostic Gateway

Build `gateway/` at the b1e55ed level, not `integrations/deerflow/gateway/`. Any client — DeerFlow, OpenClaw, a future harness, a direct API consumer — goes through the same gateway. Coupling access control to one integration creates parallel maintenance burden.

Gateway scope (< 500 LOC, FastAPI):
- Per-user API keys with permission scopes (analyst: read+submit, PM: read+approve, risk: read+veto)
- Signal approval workflow: analyst submits → PM approves → Brain ingests
- Audit log per user action
- Harness-agnostic: sits in front of b1e55ed's MCP server regardless of what's calling it

### Artifact Distribution — b1e55ed Scope, Not DeerFlow Scope

**Correction from v2:** SendGrid/SES, Slack webhooks, permalink generation — none of this is DeerFlow's responsibility. DeerFlow writes artifacts to its sandbox filesystem. b1e55ed's producer picks them up.

**The right boundary:**
1. DeerFlow writes artifact file to sandbox
2. `deerflow_research.py` picks it up, hashes it, stores it in b1e55ed's artifact store
3. b1e55ed's artifact pipeline handles distribution (email, webhook, permalink)

This is a b1e55ed sprint, not a DeerFlow integration sprint. Renamed accordingly.

### Deployment Topology

Don't try to nest Docker compositions. DeerFlow 2.0 has its own Docker setup with sandbox provisioner and frontend — nesting creates port conflicts, volume mount complexity, and operational overhead.

**Instead:** Document how to point a standalone DeerFlow instance at b1e55ed's MCP endpoint via `extensions_config.json`. Operators manage their own deployment topology. The integration is a config file, not a docker-compose.

---

## Sprint Plan (v3)

### S0 — MCP API + Signal Architecture
**Branch:** `feat/deerflow/s0`
**Prerequisite for everything else. Signal trust layer before any producer.**

- [ ] Signal class taxonomy: add `signal_class` field to event schema with schema-level validation
  - `observation`: directional claim forbidden in schema
  - `detection`: event timestamp required
  - `conviction`: falsifiable prediction + time horizon required
- [ ] Volume-dampened karma: frequency penalty per (producer, symbol) pair — not per producer globally
- [ ] LLM karma ceiling: configurable max karma for `source_type: llm_research`, rises with outcome validation
- [ ] New composable MCP tools (replacing monolithic narrator context):
  - `get_regime_status` — current regime, kill switch, trend direction
  - `get_top_signals` — recent signals, domain-filtered, cursor-paginated
  - `get_open_positions` — live book with P&L
  - `get_signals_by_domain` with bulk historical export support (for backtest use cases — not just pagination)
  - `get_regime_history` — 7-day regime trend
  - `submit_research_signal` — typed, validated, requires signed `operator_node_id`, enforces signal_class schema
- [ ] New event type: `signal.research.v1` with `ResearchSignalPayload`:
  - `symbol`, `confidence` (0-1), `direction`, `horizon`, `rationale`, `sources[]`
  - `signal_class` (observation/detection/conviction)
  - `operator_node_id` (signed)
  - `deerflow_task_id` (for artifact linkage)
- [ ] Test bulk historical data export at scale (90 days of signal history via paginated MCP — measure latency)

**What's explicitly NOT in S0:** MCP tool description rewrites for LLM discoverability. That effort belongs in skill files (S1), not tool descriptions.

---

### S1 — DeerFlow Skill Pack
**Branch:** `feat/deerflow/s1`

`skills/b1e55ed/` directory — installable as DeerFlow custom skills.

**Before writing:** Read DeerFlow's existing `skills/public/` files. Follow their exact structure. The coordinator parses a specific format — don't invent a new one.

**Model selection in all skills:** Specify coordinator model (strong — Claude Sonnet or equivalent) and data-gathering steps (cheap — flash/haiku equivalent). Don't run Opus for every sub-step.

**Error handling in all skills:** Each MCP call has explicit retry (2x) and fallback behavior (log failure, produce partial artifact with gap noted, don't silently skip). Define what a degraded output looks like.

**Memory configuration in all skills:** Define what DeerFlow should persist to long-term memory after each run (prior regime, prior conviction per symbol, prior signals used). Research should evolve across cycles, not restart cold.

---

**`research/SKILL.md`** — Core skill. Structured research plan:
1. `get_regime_status` → current context (persist to memory if changed)
2. `get_top_signals` (domain=onchain) → existing on-chain signals for symbol
3. Web search: price action, CT sentiment, news, on-chain highlights
4. Synthesize: compare current findings to prior cycle memory (delta analysis)
5. `submit_research_signal` with `operator_node_id`, `signal_class` per schema
6. Write artifact to sandbox filesystem (structured HTML)
7. Persist to memory: regime, conviction, key findings

**`brief/SKILL.md`** — Daily IC brief:
1. `get_regime_status` → regime context
2. `get_top_signals` → top signals across domains
3. `get_open_positions` → live book
4. Web search: top 24h news
5. Delta vs. prior memory: what changed since yesterday's brief
6. Synthesize → polished HTML brief
7. Write to sandbox filesystem (b1e55ed producer picks it up)
8. Persist to memory: brief summary for next cycle delta

**`thesis/SKILL.md`** — Structured thesis evaluation:
1. Accept token + thesis text
2. `get_top_signals` for symbol
3. Web research: evidence for/against
4. Score: narrative / on-chain / technical / risk (0-10 each)
5. `submit_research_signal` with `signal_class: conviction`, falsifiable horizon
6. Return formatted evaluation with score breakdown

**`backtest/SKILL.md`** — Natural language backtest:
1. Parse strategy description → parameters
2. `get_signals_by_domain` bulk export for historical data (via new bulk endpoint)
3. Write Python backtest script to sandbox
4. Execute in DeerFlow sandbox (isolated — can only access b1e55ed via MCP, not direct import)
5. Return results as formatted report + artifact

**`watchlist/SKILL.md`** — Parallel coverage:
1. Accept watchlist from DeerFlow memory or explicit list
2. Coordinator decomposes into sequential/parallel research steps per token
3. Per-token: research skill workflow (condensed)
4. Rank by conviction delta (vs. prior memory)
5. Return ranked list + trigger brief skill for top picks
6. Persist updated per-token conviction to memory

---

### S1.5 — b1e55ed Artifact Pipeline (renamed from "distribution")
**Branch:** `feat/deerflow/s1.5`
**b1e55ed scope, not DeerFlow scope.**

- [ ] `deerflow_research.py` producer picks up artifact from DeerFlow sandbox (via API or mounted volume)
- [ ] Hash artifact, store in b1e55ed artifact store, permalink generation
- [ ] Artifact event: every artifact linked to the `signal.research.v1` event that generated it
- [ ] Distribution triggers from b1e55ed side: email (SendGrid/SES), Slack/Teams webhook
- [ ] Artifact template config: logo, branding, risk category labels — configurable without code changes
- [ ] Retrieval: artifact permalink stored in event payload → "why did we write this 6 months ago?" answerable

---

### S2 — Integration Config + Harness-Agnostic Gateway
**Branch:** `feat/deerflow/s2`

- [ ] `gateway/` at b1e55ed root (not under integrations/deerflow):
  - FastAPI, < 500 LOC
  - Per-user API keys (analyst/PM/risk roles)
  - Role-based MCP tool filtering
  - Signal approval workflow
  - Audit log per user action
  - Harness-agnostic: any client routes through it
- [ ] `integrations/deerflow/extensions_config.json` — ready-to-use DeerFlow MCP config pointing at b1e55ed endpoint
- [ ] `docs/deerflow.md` — Operator guide: how to point a standalone DeerFlow at b1e55ed (config file, not docker-compose)
- [ ] Mintlify nav update

**Explicitly dropped:** `docker-compose.yml` bundling b1e55ed + DeerFlow together. Too complex, wrong boundary. Operators manage deployment topology.

---

### S3 — Research Producer
**Branch:** `feat/deerflow/s3`
**Depends on S0 (signal architecture), S1 (skill pack), S2 (connection + gateway).**

- [ ] `engine/producers/deerflow_research.py` — async trigger-and-wait producer:
  - Schedule: `0 */6 * * *`
  - Reads active universe from brain (top tokens by conviction activity)
  - Calls DeerFlow watchlist skill via API
  - Polls for completion (timeout: 30 min)
  - Picks up artifact from sandbox
  - Hashes + stores artifact (S1.5 pipeline)
  - Ingests final synthesized signal as `signal.research.v1`
  - Logs artifact permalink to event payload
- [ ] Degradation handling: if DeerFlow MCP calls fail mid-cycle → partial artifact flagged, cycle logged, no silent skip
- [ ] Dashboard: `signal.research.v1` in signals page domain filter
- [ ] Dashboard: research artifact preview panel (link to permalink)

---

## Sprint Order and Dependencies

```
S0 (MCP API + signal architecture)
    │   ← Signal trust layer first. No exceptions.
    │
    ├─────────────────────────────────────┐
    ▼                                     ▼
S1 (skill pack)                    S1.5 (artifact pipeline — b1e55ed side)
    │                                     │
    └──────────────┬──────────────────────┘
                   ▼
            S2 (integration config + gateway)
                   │
                   ▼
            S3 (research producer)
                   │
                   ▼
     [end-to-end: DeerFlow watchlist →
      parallel research (evolving from memory) →
      signal.research.v1 + artifact →
      distribution pipeline]
```

S1 and S1.5 can run in parallel (no shared files).
S0 must complete before S3 starts.

---

## Kill List

| Item | Why Killed |
|------|-----------|
| **S4 — Retail UI Wrapper** | Strategically wrong. Regulatory risk. Dilutes moat. |
| **`get_narrator_context` monolith** | Anti-pattern for DeerFlow's composable coordinator |
| **MCP description rewrites for "LLM discoverability"** | Misunderstood how DeerFlow selects tools — skill files drive this, not tool descriptions |
| **`integrations/deerflow/gateway/`** | Gateway is harness-agnostic — lives at `gateway/` root |
| **docker-compose bundling** | Wrong boundary. Operators manage topology. Config file is the integration. |

---

## Competitive Differentiation

Three genuine moats:
1. **Sovereignty** — you own the stack, your alpha doesn't leak to a vendor's other clients
2. **Automated synthesis** — the Brain synthesizes multi-domain signals into regime-conditioned conviction; no competitor does this
3. **Cryptographic audit trail** — hash chain answers "why did we make this trade 6 months ago?" — no competitor can

Don't compete on data breadth. Compete on synthesis, sovereignty, and provenance.

---

## Success Metrics

- [ ] Composable MCP tools working: DeerFlow coordinator calls get_regime_status + get_top_signals + get_open_positions independently per task need
- [ ] Signal class taxonomy enforced at schema level — observation cannot contain directional claim
- [ ] DeerFlow research skill produces valid `signal.research.v1` with signed `operator_node_id`
- [ ] Research memory persists across 6h cycles — delta analysis working (not cold-start each run)
- [ ] Daily brief artifact delivered via email/Slack from b1e55ed artifact pipeline
- [ ] Artifact permalink stored in event chain, retrievable 6 months later
- [ ] Gateway handling analyst/PM role separation for any harness
- [ ] Degradation handling: partial artifact produced and flagged when MCP calls fail mid-cycle

---

*Three versions. External DeerFlow-perspective review applied. The integration surface is right: skills + composable MCP + aggregated signals. The execution plan now reflects how DeerFlow 2.0 actually works.*
