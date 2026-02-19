# Operator Layer Sprint Plan (beta.2)

**Goal**: Agents and humans can install and operate b1e55ed through conversation.

**Design principle**: The agent IS the operator layer. No middleware. No SDK. CLI-first. The "integration" is a markdown file that teaches any agent how to operate the engine.

**Gate**: Fresh OpenClaw install → `clawhub install b1e55ed` → agent operates within 5 minutes.

---

## Architecture

```
┌──────────────────────────────────────────────┐
│          OPERATOR (Human or Agent)            │
│                                               │
│   Reads SKILL.md → knows how to operate       │
│   Uses CLI commands → controls the engine     │
│   Receives alerts → routes to chat/webhook    │
└───────────────┬──────────────────────────────┘
                │  Shell commands (local)
                │  HTTP API (remote/dashboard)
                ▼
┌──────────────────────────────────────────────┐
│              b1e55ed ENGINE                    │
│                                               │
│   CLI ←→ Core ←→ API                          │
│                                               │
│   Producers → Brain → Conviction → Execution  │
│   Events → Learning Loop → Corpus             │
└──────────────────────────────────────────────┘
```

**Two operator modes:**
- **Local** (CLI): `b1e55ed brain`, `b1e55ed signal "..."`, `b1e55ed alerts`
- **Remote** (API): `POST /brain/run`, `POST /signals/curator`, `GET /alerts`

Same engine, same events, same outputs. The CLI wraps the same code the API calls.

---

## Sprint O1: CLI + Skill Package (Foundation)

**Goal**: Complete CLI + SKILL.md. An agent that reads SKILL.md can operate b1e55ed.

### CLI Extensions

| Command | Purpose | Output |
|---------|---------|--------|
| `b1e55ed signal "text"` | Ingest operator intel as curator signal | JSON event confirmation |
| `b1e55ed signal add --file <path>` | Ingest from file (multi-line, links) | JSON event confirmation |
| `b1e55ed alerts` | List active alerts (stops, targets, kill switch) | Human-readable table |
| `b1e55ed alerts --json` | Machine-readable alerts | JSON array |
| `b1e55ed positions` | List open positions with P&L | Human-readable table |
| `b1e55ed positions --json` | Machine-readable positions | JSON array |
| `b1e55ed kill-switch` | Show current kill switch level | Level + reason |
| `b1e55ed kill-switch set <0-4>` | Set kill switch level (operator override) | Confirmation |
| `b1e55ed brain --full` | Run full cycle including slow producers | Brain result |
| `b1e55ed brain --json` | Machine-readable brain output | JSON |
| `b1e55ed health` | System health check (for cron/heartbeat) | JSON health object |

**All commands support `--json` for machine consumption.** Default is human-readable.

### SKILL.md

The operator manual. Teaches any agent how to run b1e55ed. Sections:

1. **What this is** — one paragraph
2. **Quick start** — `b1e55ed setup && b1e55ed brain`
3. **Commands** — full CLI reference
4. **Heartbeat protocol** — what to check on each poll
5. **Signal detection** — when/how to ingest operator intel
6. **Alert routing** — how to deliver alerts to operator
7. **Cron schedule** — recommended automation

### setup.sh

One-command install for fresh systems:

```bash
curl -sSf https://raw.githubusercontent.com/P-U-C/b1e55ed/main/scripts/install.sh | bash
```

Detects OS, installs Python/uv if needed, clones repo, runs `b1e55ed setup`.

### crons.json

Importable cron job definitions for OpenClaw:

```json
[
  { "name": "Brain Cycle", "schedule": "*/30 * * * *", "command": "b1e55ed brain" },
  { "name": "Full Sweep", "schedule": "0 */6 * * *", "command": "b1e55ed brain --full" },
  { "name": "Morning Summary", "schedule": "0 13 * * *", "command": "b1e55ed health --json" },
  { "name": "Evening Wrap", "schedule": "0 2 * * *", "command": "b1e55ed health --json" }
]
```

### Tests

- [ ] All new CLI commands have unit tests
- [ ] `b1e55ed health` returns valid JSON in all states (fresh install, running, degraded)
- [ ] `b1e55ed signal` creates events in the DB
- [ ] `b1e55ed alerts --json` + `b1e55ed positions --json` parseable by agents
- [ ] SKILL.md passes brand vocabulary check
- [ ] E2E: fresh `b1e55ed setup` → `b1e55ed brain` → `b1e55ed alerts` works

### Acceptance

An OpenClaw agent that has never seen b1e55ed before can:
1. Read SKILL.md
2. Run `b1e55ed setup --preset balanced --non-interactive`
3. Run `b1e55ed brain` and get a result
4. Run `b1e55ed alerts` and understand the output
5. Run `b1e55ed signal "BTC looking strong, ETF inflows 3 days running"` and see it ingested

---

## Sprint O2: Signal Flow (Chat → Engine → Chat)

**Goal**: Closed loop. Drop intel in chat, get alerts back in chat.

### `/signal` Handler

SKILL.md already teaches signal detection. This sprint adds:

- **Accumulator**: 60-second window for multi-message intel (operator often sends 2-3 messages about the same thing)
- **Auto-detection heuristic**: defined in SKILL.md, executed by the agent
  - Contains ticker symbol + directional language → signal
  - Contains link to chart/thread + commentary → signal
  - Prefixed with `/signal` → always signal
- **Structured output**: agent runs `b1e55ed signal "..."` with the accumulated text

### Alert Routing

- `b1e55ed alerts --watch` — blocking command that emits alerts as they occur (SSE-style)
- Or: agent polls `b1e55ed alerts --json` on heartbeat (simpler, recommended)
- SKILL.md defines routing: critical → immediate message, standard → batch in summary, low → log only

### Event Webhooks

For non-OpenClaw agents and external systems:

```bash
b1e55ed webhooks add <url> --events "alert.*,kill_switch.*"
b1e55ed webhooks list
b1e55ed webhooks remove <id>
```

Engine POSTs JSON events to registered URLs when matching events occur.

Implementation: lightweight webhook dispatcher in `engine/integration/webhooks.py`. Stores subscriptions in brain.db. Fires on event commit. Retry with exponential backoff (3 attempts).

### Tests

- [ ] Signal ingestion from CLI creates proper curator events
- [ ] Webhook fires on alert events
- [ ] Webhook retries on failure (3x backoff)
- [ ] Webhook subscription CRUD via CLI
- [ ] E2E: `b1e55ed signal "..."` → brain cycle → alert generated → webhook fires

---

## Sprint O3: Agent Interface (Machine-Readable)

**Goal**: Other agents can discover, connect to, and contribute to b1e55ed programmatically.

### OpenAPI Spec

FastAPI already auto-generates OpenAPI. This sprint:

- [ ] Verify all endpoints have proper request/response schemas
- [ ] Add examples to each endpoint
- [ ] Publish at `/docs` (Swagger UI) and `/openapi.json` (raw spec)
- [ ] Version the API (`/api/v1/`)

### Producer Registration API

Agents can add signal sources at runtime:

```bash
# Via CLI
b1e55ed producers register --name "my-scanner" --domain technical --endpoint http://localhost:9000/signals

# Via API
POST /api/v1/producers/register
{
  "name": "my-scanner",
  "domain": "technical",
  "endpoint": "http://localhost:9000/signals",
  "schedule": "*/15 * * * *"
}
```

Engine polls registered producer endpoints on schedule, ingests structured signals.

Producer contract (what the endpoint must return):

```json
{
  "producer": "my-scanner",
  "domain": "technical",
  "signals": [
    {
      "asset": "BTC",
      "direction": "bullish",
      "score": 7.2,
      "confidence": 0.8,
      "reasoning": "Golden cross on daily"
    }
  ]
}
```

### Structured Errors

All API responses use consistent error format:

```json
{
  "error": {
    "code": "KILL_SWITCH_ACTIVE",
    "message": "Kill switch at level 3. No new intents accepted.",
    "level": 3
  }
}
```

### CONTRIBUTING.md

How to contribute to b1e55ed:

1. **Add a producer** — implement the producer interface, register via CLI/API
2. **Add a strategy** — implement the strategy interface, add to config
3. **Add a sample pack** — create a samples/{domain}/ directory with README
4. **Improve docs** — follow brand vocabulary, run CI checks
5. **Report bugs** — issue template with reproduction steps

### Tests

- [ ] OpenAPI spec validates against schema
- [ ] Producer registration creates and polls new producer
- [ ] Producer deregistration stops polling
- [ ] Error responses follow consistent format
- [ ] CONTRIBUTING.md passes brand check

---

## Sprint O4: Distribution + Integration Testing

**Goal**: Installable via ClawHub. Battle-tested integration.

### ClawHub Publication

```bash
clawhub publish b1e55ed
```

Package structure:

```
b1e55ed/
├── SKILL.md            # Agent instructions
├── setup.sh            # One-command install
├── crons.json          # Importable cron templates
├── skill.json          # ClawHub metadata (name, version, description, tags)
└── README.md           # Human-readable overview
```

`skill.json`:

```json
{
  "name": "b1e55ed",
  "version": "1.0.0-beta.2",
  "description": "Sovereign AI trading intelligence with compound learning",
  "tags": ["trading", "crypto", "intelligence", "compound-learning"],
  "author": "Permanent Upper Class",
  "repository": "https://github.com/P-U-C/b1e55ed",
  "requires": ["python>=3.11"]
}
```

### Integration Tests

| Test | What | Pass Criteria |
|------|------|---------------|
| Fresh install | `clawhub install b1e55ed` on clean system | Setup completes, brain runs |
| Chat → signal → brain → alert → chat | Full closed loop | Alert delivered within 1 brain cycle |
| Multi-agent curation | 2 agents POST signals simultaneously | Both signals in brain, no conflicts |
| Graceful degradation | Kill API mid-cycle | Engine completes cycle, CLI still works |
| Webhook delivery | Register webhook, trigger alert | POST received with correct payload |
| Producer registration | Register external producer, run brain | External signals included in synthesis |
| Cold start | No API keys, no data | Setup completes, brain runs with available producers only |

### Agent-as-Producer Tutorial

`docs/tutorial-agent-producer.md`:

Step-by-step guide for building an agent that contributes signals to b1e55ed:

1. Understand the producer contract (JSON schema)
2. Build a minimal signal endpoint (10 lines of Python)
3. Register with `b1e55ed producers register`
4. Verify signals are ingested
5. Monitor producer health via `b1e55ed status`

---

## Sequence

```
O1 (CLI + Skill)  ──→  O2 (Signal Flow)  ──→  O3 (Agent Interface)  ──→  O4 (Distribution)
   Foundation            Closed Loop            Machine-Readable           Ship It
   ~1 day                ~1 day                 ~1 day                     ~0.5 day
```

**Total estimate: 3-4 days** at our build velocity.

---

## Design Decisions

### CLI-first, not API-first
The primary operator (human or OpenClaw agent) is local. CLI is the natural interface — no auth, no network, self-documenting, pipeable. The API exists for dashboards, remote agents, and the future network.

### SKILL.md is the integration
No SDK. No wrapper library. No custom runtime. The agent reads a markdown file and knows how to operate the engine. This is radically minimal and works with any agent platform that can run shell commands.

### `--json` everywhere
Every CLI command supports `--json` for machine consumption. Default output is human-readable. This means the same commands work for both operator modes without a separate "machine API."

### Webhook over polling for external agents
Internal operators (OpenClaw) poll on heartbeat — simple, reliable, no extra infrastructure. External agents get webhooks — push-based, real-time, standard HTTP. Both supported, neither required.

### Producer contract is HTTP + JSON
Any system that can serve an HTTP endpoint returning JSON can be a producer. No protocol buffers. No gRPC. No message queues. Just HTTP. This maximizes the number of agents and systems that can contribute signals.

---

## What's NOT in beta.2

| Item | Why Not | When |
|------|---------|------|
| MCP server | Nice-to-have, not blocking adoption | v1.1 |
| Multi-exchange | Hyperliquid-only is fine for beta | v1.1 |
| Mobile dashboard | Responsive CSS is sufficient | v1.1 |
| Strategy marketplace | Need more strategies first | v1.2 |
| Token-gated access | No token yet | Post-1.0 |

---

## Success Criteria

beta.2 is done when:

1. ✅ `clawhub install b1e55ed` works on a fresh system
2. ✅ An agent with no prior knowledge reads SKILL.md and operates the engine
3. ✅ Chat → signal → brain → alert → chat loop works end-to-end
4. ✅ An external agent can register as a producer and contribute signals
5. ✅ All integration tests pass
6. ✅ CONTRIBUTING.md exists and is accurate

---

*The operator layer is 200 lines of CLI + 1 markdown file + 1 shell script. The agent does the rest. That's the point.*
