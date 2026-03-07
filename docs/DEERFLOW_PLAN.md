# DeerFlow × b1e55ed — Integration Plan (v2)

> **Status:** Planning — 2026-03-07 (revised after dual model analysis)
> **Models consulted:** Opus 4.6 × 2 (independent research sessions)
> **Branch strategy:** `feat/deerflow` → `develop`

---

## Corrected Framing

b1e55ed is harness-agnostic. The event core, brain, MCP server — none of it cares what's on top.

Two harnesses. Different institutional roles.

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
     Telegram alerts                 IC-ready reports, PDFs, dashboards
     Heartbeats, positions           Scheduled research pipelines
     "What do I do right now?"       "Give me full coverage on 30 tokens"
```

**There is no retail layer.** That's a separate product category with regulatory implications b1e55ed isn't positioned for. Kill S4 (Retail UI Wrapper) — it's strategically incoherent. If retail emerges, it's a third-party wrapper consuming the Oracle API, not b1e55ed shipping a chat UI.

---

## What DeerFlow Actually Opens Up

### 1. Systematic Token Coverage at Scale
A 3-person fund managing $100M can't research 30 tokens manually. DeerFlow parallelizes: one sub-agent per token, all running concurrently, synthesized into a ranked conviction output. The research throughput of an 8-person team, automated.

This didn't exist before. Not in OpenClaw (synchronous, operator-initiated), not in any competitor (platforms give data, not synthesis).

### 2. Investment Committee Artifacts
IC prep is currently manual everywhere. DeerFlow generates: regime overview + top signals + position rationale + risk summary → HTML brief or PDF. Scheduled. Shareable. Timestamped. Tied to b1e55ed's hash chain.

One genuine gap: **distribution**. Artifacts sitting in a Docker volume are worthless. See Sprint S1.5 below.

### 3. Sandboxed Quant Execution
"Backtest SOL momentum for 90 days using b1e55ed's signal history" → DeerFlow writes and executes the Python in a Docker sandbox, returns results as a formatted report. b1e55ed's backtest engine already exists. DeerFlow wraps it in natural language and returns a shareable artifact.

### 4. Skills as Producer Templates
DeerFlow's SKILL.md system maps to b1e55ed producers. Any analyst can write a skill file (no Python) and become a signal producer. Opens the contributor surface massively without requiring engineering.

### 5. LP/Investor Reporting
Quarterly LP updates are currently labor-intensive at small funds. DeerFlow generates structured performance attribution, strategy narrative, and forward outlook — all grounded in b1e55ed's hash-chained event history. Audit-defensible by construction.

### 6. Local Model Support for Compliance
TradFi desks entering crypto need on-premise models for compliance. DeerFlow supports local models (Ollama, etc.). b1e55ed's MCP server is model-agnostic. Together: a fully self-hostable institutional intelligence stack. No data leaves the building.

---

## Target Customer

Not Bloomberg Terminal customers. Not Paradigm (they build proprietary). Not retail.

**The beachhead:** 3-10 person crypto fund, $50-200M AUM, conviction-based strategy, no dedicated quant team. They have capital and edge but are drowning in information. DeerFlow gives them research throughput. b1e55ed gives them systematic synthesis. Together: the infrastructure they couldn't afford to build.

Secondary: Crypto-native research shops (Delphi-tier) needing a content production pipeline with signal provenance.

---

## Competitive Differentiation

| Capability | Messari | Nansen | Kaito | The Tie | b1e55ed+DeerFlow |
|-----------|---------|--------|-------|---------|-----------------|
| Data breadth | ✅ | ✅ | ✅ | ✅ | ❌ (your producers) |
| Research quality | ✅ Human | ⚠️ Data only | ⚠️ LLM | ✅ Human+quant | ⚠️ LLM (honest) |
| **Sovereignty** | ❌ Platform | ❌ Platform | ❌ Platform | ❌ Platform | ✅ **Own your stack** |
| **Signal synthesis** | ❌ Manual | ❌ Manual | ❌ Manual | ❌ Manual | ✅ **Brain is unique** |
| **Provenance chain** | ❌ | ❌ | ❌ | ❌ | ✅ **Hash chain** |
| **Automation** | ❌ | ❌ | ❌ | ❌ | ✅ **End-to-end** |
| Cost | $25K+/yr | $10K+/yr | $5K+/yr | $30K+/yr | Self-hosted |

Three genuine moats: **sovereignty** (you own it, your alpha doesn't leak), **automated synthesis** (Brain is nowhere else), **cryptographic audit trail** (no competitor can answer "why did we enter 6 months ago?" with a hash chain).

Don't compete on data breadth — you'll lose. Compete on synthesis, sovereignty, and provenance.

---

## Critical Architecture Decisions

### Signal Trust — The Drowning Problem

DeerFlow could generate 50+ research signals/day. The karma/flywheel system was designed for sparse, high-quality on-chain signals. High-volume LLM-generated research will corrupt Brain conviction if not architected correctly.

**Required before S3:**

**Signal class taxonomy** — explicit tiers, different brain weights:
- `signal.observation` — "here's what I found" (DeerFlow research, social scans). Low weight. Informs.
- `signal.detection` — "something happened" (on-chain events, price movement). Medium weight. Triggers.
- `signal.conviction` — "I believe X with evidence" (scored thesis, validated by outcome). High weight. Drives.

**Volume-dampened karma** — karma per signal is inversely proportional to signal frequency. A producer emitting 50/day earns less karma per signal than one emitting 3/day. Basic information theory: high-frequency signals carry less information per unit.

**LLM karma ceiling** — DeerFlow signals have a hard karma cap until validated by outcomes. Prevents a well-configured DeerFlow from dominating Brain conviction before it's earned it.

### Sub-Agent Model → Producer Model

Don't map DeerFlow sub-agents 1:1 to b1e55ed producers. That breaks both models.

**The right pattern:** One DeerFlow task = one b1e55ed event. The aggregator pattern.

```
DeerFlow Skill: "Research $TOKEN"
    ├── Sub-agent: gather on-chain data
    ├── Sub-agent: analyze social/CT sentiment
    ├── Sub-agent: review tokenomics + narrative
    └── Coordinator: synthesize → ResearchSignalPayload
                         │
                         ▼
          signal.research.v1 → b1e55ed (one event)
          + Artifact (PDF/HTML) → storage + distribution
```

`deerflow_research.py` in b1e55ed is a thin async trigger-and-wait wrapper. It calls DeerFlow, polls for completion, ingests the final synthesized output. Sub-agent internals are DeerFlow's problem. The `sources[]` array on the signal payload provides provenance without polluting the event stream.

### Identity and Attribution

When DeerFlow emits a signal into b1e55ed, who earns karma?

**Wrong answers:** DeerFlow the system (a tool doesn't have agency), the sub-agent (ephemeral, no continuity), the model (can't be held accountable).

**Right answer: the human operator who configured and deployed the DeerFlow skill.** They made the judgment call to run this skill on this watchlist at this schedule. They own the outcome.

**Architecture:**
- DeerFlow skills must carry `operator_node_id` — the b1e55ed forge identity of the human who set it up
- `submit_research_signal` requires `operator_node_id` as a signed field
- Karma flows to that node, not to "deerflow" as a system actor
- This preserves flywheel integrity: human judgment → outcome → karma → weight

### Multi-Tenancy

b1e55ed is single-operator. Institutional teams need role separation.

**Don't build RBAC into b1e55ed core** — it would take 6 months and complicate the protocol.

**Build a lightweight API gateway** (< 500 LOC, FastAPI) between DeerFlow and b1e55ed's MCP server:
- Per-user API keys with permission scopes (analyst: read+submit, PM: read+approve, risk: read+veto)
- Signal approval workflow: analyst submits → PM approves → Brain ingests
- Audit log per user action
- Role-filtered MCP tool exposure

b1e55ed stays sovereign and single-operator. The gateway mediates institutional access. Add to S2.

---

## Sprint Plan (Revised)

### S0 — MCP Hardening + Signal Architecture
**Branch:** `feat/deerflow/s0`
**Prerequisite for everything else.**

- [ ] Signal class taxonomy: add `signal_class` field (observation/detection/conviction) to event schema
- [ ] Volume-dampened karma: frequency penalty in karma calculation
- [ ] LLM signal karma ceiling: configurable max karma for `source_type: llm_research`
- [ ] New MCP tools:
  - `get_signals_by_domain` with cursor-based pagination
  - `get_regime_history` (7-day trend, not just current state)
  - `submit_research_signal` — typed, validated, requires `operator_node_id`
  - `get_narrator_context` — pre-packaged LLM context block (regime + top 3 signals + positions, < 500 tokens)
- [ ] Rewrite all MCP tool descriptions for LLM discoverability (DeerFlow auto-discovers at runtime)
- [ ] New event type: `signal.research.v1` with `ResearchSignalPayload`

**Why signal architecture is in S0:** Build the producer before the trust layer and you'll corrupt the Brain from day one.

---

### S1 — DeerFlow Skill Pack
**Branch:** `feat/deerflow/s1`

`skills/b1e55ed/` directory — installable as DeerFlow custom skills.

**`research/SKILL.md`** — Core skill. Given symbol(s):
1. `get_brain_status` → current regime context
2. Parallel sub-agents: on-chain data, social/CT sentiment, tokenomics/narrative
3. Synthesize → `ResearchSignalPayload`
4. `submit_research_signal` with `operator_node_id`
5. Generate research artifact (HTML, structured)

**`brief/SKILL.md`** — Daily IC brief:
1. `get_narrator_context` → regime + signals
2. `get_open_positions` → live book
3. Web search: top 24h news
4. Synthesize → polished HTML brief (dark mode, b1e55ed aesthetic)
5. Write to sandbox → hand off to distribution pipeline (S1.5)

**`thesis/SKILL.md`** — Structured thesis evaluation:
1. Accept token + thesis text
2. Research via web + `get_recent_signals`
3. Score: narrative / on-chain / technical / risk
4. `submit_research_signal` with `signal_class: conviction`
5. Return formatted evaluation

**`backtest/SKILL.md`** — Natural language backtest:
1. Parse strategy description → parameters
2. `get_signals_by_domain` for historical signal data
3. Write + execute Python in DeerFlow sandbox
4. Return formatted results + artifact

**`watchlist/SKILL.md`** — Parallel coverage:
1. Accept watchlist (from DeerFlow memory or explicit)
2. Spawn parallel research sub-agents (one per token)
3. Rank by conviction
4. Return ranked list with rationale + trigger brief skill for top picks

---

### S1.5 — Artifact Distribution Pipeline
**Branch:** `feat/deerflow/s1.5`
**NEW — not in original plan. Critical for institutional value.**

Artifacts sitting in a Docker volume are worthless. Institutions need delivery.

- [ ] Email delivery: SendGrid/SES integration — brief lands in PM inbox at 7:00 AM local
- [ ] Webhook: Slack/Teams compatible — brief posts to team channel
- [ ] Permalink: every generated artifact gets a unique URL, stored in b1e55ed event chain with hash
- [ ] Artifact template system: configurable logo, branding, risk category labels (no code change required)
- [ ] Retention: artifacts linked to the events that generated them — "why did we write this?" is answerable

Without this sprint, S1 is a content engine with no audience.

---

### S2 — Integration Config + API Gateway
**Branch:** `feat/deerflow/s2`

- [ ] `integrations/deerflow/extensions_config.json` — ready-to-use DeerFlow MCP config with b1e55ed endpoint + auth
- [ ] `integrations/deerflow/gateway/` — lightweight FastAPI API gateway (< 500 LOC):
  - Per-user API keys (analyst/PM/risk roles)
  - Role-based MCP tool filtering
  - Signal approval workflow (analyst submits → PM approves → b1e55ed ingests)
  - Audit log per user action
- [ ] `integrations/deerflow/docker-compose.yml` — b1e55ed + DeerFlow + gateway side by side
- [ ] `integrations/deerflow/setup.sh` — one-command setup
- [ ] `docs/deerflow.md` — Operator guide
- [ ] Mintlify nav update

---

### S3 — Research Producer
**Branch:** `feat/deerflow/s3`
**Depends on S0 (signal architecture), S1 (skill pack), S2 (connection config).**

- [ ] `engine/producers/deerflow_research.py` — async trigger-and-wait producer
  - Schedule: `0 */6 * * *` (6h)
  - Reads active universe from brain (top tokens by conviction activity)
  - Calls DeerFlow watchlist skill via API
  - Polls for completion (timeout: 30 min)
  - Ingests final synthesized signal as `signal.research.v1`
  - Logs artifact permalink to event payload
- [ ] Dashboard: `signal.research.v1` in signals page domain filter
- [ ] Dashboard: research artifact preview panel (link to permalink)
- [ ] Provenance: `operator_node_id` required, karma flows to operator

---

## Sprint Order and Dependencies

```
S0 (MCP hardening + signal architecture)
    │   ← DO THIS FIRST. Signal trust layer before any producer.
    ▼
S1 (skill pack) ──────────────── S1.5 (artifact distribution)
    │                                     │
    └──────────────┬───────────────────────┘
                   ▼
               S2 (integration config + gateway)
                   │
                   ▼
               S3 (research producer)
                   │
                   ▼
         [end-to-end validation:
          DeerFlow watchlist → parallel research →
          signal.research.v1 in b1e55ed →
          brief artifact → email delivery]
```

S1 and S1.5 can run in parallel (no shared files).
S0 must complete before S3 starts.

---

## Kill List (Things Removed from Original Plan)

| Item | Why Removed |
|------|-------------|
| **S4 — Retail UI Wrapper** | Strategically wrong. Retail ≠ DeerFlow's user. Regulatory risk. Dilutes moat. |
| **"Retail-accessible UX" as goal** | Replaced with: institutional research desk automation |
| **get_narrator_context returning "retail-friendly" summaries** | Reframed: pre-packaged LLM context for analyst workflows |

---

## Success Metrics

- [ ] DeerFlow `tools/list` shows all b1e55ed MCP tools with institutional-grade descriptions
- [ ] Signal class taxonomy active — Brain weights observation/detection/conviction differently
- [ ] DeerFlow research skill produces valid `signal.research.v1` with `operator_node_id`
- [ ] Daily brief artifact delivered via email/Slack without manual intervention
- [ ] Artifact permalink stored in b1e55ed event chain (retrievable 6 months later)
- [ ] Research producer running 6h schedule, covering active universe
- [ ] API gateway handling analyst/PM role separation
- [ ] `b1e55ed start` + `setup.sh` = 2-command institutional deployment

---

*DeerFlow gives b1e55ed a research surface it can't build itself. b1e55ed gives DeerFlow's research economic teeth — signal attribution, karma, provenance, and a conviction engine that learns. Neither works as well alone.*
