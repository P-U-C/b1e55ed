# OpenClaw Integration

How b1e55ed connects to the operator layer.

---

## Two-Layer Architecture

b1e55ed is an engine, not an interface. It processes signals, runs brain cycles, and generates trade intents. But it doesn't handle conversation, curation, or operator interaction directly.

That's the operator layer's job.

```
┌─────────────────────────────────────────────┐
│            OPERATOR LAYER                    │
│                                             │
│   Chat ─── Curation ─── Control ─── Alerts  │
│                                             │
│   OpenClaw / Custom Agent / Direct API      │
└──────────────────┬──────────────────────────┘
                   │  Events + API
                   ▼
┌─────────────────────────────────────────────┐
│            b1e55ed ENGINE                    │
│                                             │
│   Producers → Brain → Conviction → Execution│
│                                             │
│   Event Store ─── Learning Loop ─── Audit   │
└─────────────────────────────────────────────┘
```

b1e55ed is designed to run under [OpenClaw](https://openclaw.ai) as a sovereign trading agent — but any system that speaks HTTP and emits events can serve as the operator layer.

---

## Integration Points

### 1. Curator Pipeline (Operator → Engine)

The curator producer accepts structured signals from the operator layer. This is how human intelligence enters the system.

**Via API:**
```bash
POST /signals/curator
{
  "content": "Whale cluster accumulating SOL — 3 wallets, $2M+ in 48h",
  "source": "operator",
  "assets": ["SOL"],
  "direction": "bullish",
  "conviction": 7
}
```

**Via OpenClaw:**
Operator drops alpha in chat. The `/signal` command (or auto-detection) classifies, structures, and forwards to the curator endpoint. Multi-message accumulation with a 60-second window handles the natural rhythm of human intel sharing.

**Via Agent:**
Any agent that can POST JSON can curate. The schema is the same regardless of who's sending it — human or machine.

### 2. Brain Control (Operator → Engine)

```bash
# Trigger brain cycle
POST /brain/run

# Check status
GET /brain/status

# Kill switch override (operator-only, requires auth)
POST /brain/kill-switch
{ "level": 0, "reason": "Manual reset after review" }
```

### 3. Alerts (Engine → Operator)

The engine emits alert events. The operator layer decides how to deliver them:

| Alert | Event Type | Urgency |
|-------|-----------|---------|
| Stop hit | `alert.stop_triggered` | Immediate |
| Target reached | `alert.target_hit` | Immediate |
| Kill switch escalation | `alert.kill_switch` | Immediate |
| Regime change | `alert.regime_shift` | Standard |
| Learning loop update | `alert.weights_adjusted` | Low |

OpenClaw routes these to Telegram, Discord, or wherever the operator lives. A custom integration reads the event stream and routes however it wants.

### 4. Dashboard (Passive Monitoring)

The web dashboard at `localhost:5051` provides real-time visualization. It reads the same event store — no special integration needed. Works alongside any operator layer.

---

## OpenClaw Skill (Next Phase)

The planned OpenClaw skill package will provide:

| Component | Purpose |
|-----------|---------|
| `SKILL.md` | Agent instructions for operating b1e55ed |
| Cron templates | Brain cycle, monitoring sweep, daily summaries |
| Heartbeat checks | Position alerts, system health |
| `/signal` handler | Chat → curator pipeline |
| Alert routing | Engine events → chat notifications |

This makes b1e55ed installable as a skill — one command to give any OpenClaw agent trading intelligence.

---

## Agent-First Design

b1e55ed treats agents as first-class operators, not just API consumers.

**For agents integrating b1e55ed:**

- **Discovery**: Standard REST API with OpenAPI schema at `/docs`
- **Authentication**: Bearer token, same for humans and agents
- **Event format**: JSON events with consistent schema, hash-chained for auditability
- **Idempotency**: All write operations are idempotent — safe for retry-happy agents
- **Structured errors**: Machine-readable error responses with error codes

**For agents contributing to b1e55ed:**

- **Custom producers**: Implement the producer interface, register via config
- **Signal submission**: POST to `/signals/{producer_id}` with structured data
- **Strategy plugins**: Implement the strategy interface for custom brain logic

The event contract is the universal integration point. If you can emit a JSON event, you can participate in the system.

---

## Integration Patterns

### Pattern 1: Headless (API Only)

```
Your Code → HTTP → b1e55ed API → Brain → Events
```

No operator layer. Direct API calls. Good for backtesting, CI pipelines, or embedding b1e55ed in a larger system.

### Pattern 2: Agent-Operated (OpenClaw)

```
Chat → OpenClaw → b1e55ed API → Brain → Events → OpenClaw → Chat
```

Full conversational loop. Drop alpha, get alerts, control the system through natural language. The intended production setup.

### Pattern 3: Multi-Agent

```
Agent A (Research) → Curator API ──┐
Agent B (On-chain) → Curator API ──┤→ Brain → Conviction → Execution
Agent C (Social)   → Curator API ──┘
         Operator  → Control API ──→ Override / Kill Switch
```

Multiple agents feeding signals. One operator with kill switch authority. The compound learning loop benefits from every participant.

---

## What's Not Built Yet

Transparency about current state:

| Component | Status | Phase |
|-----------|--------|-------|
| REST API | ✅ Live | Current |
| Dashboard | ✅ Live | Current |
| Event store | ✅ Live | Current |
| Curator endpoint | ✅ Live | Current |
| OpenClaw skill package | ⬜ Planned | Next |
| `/signal` chat handler | ⬜ Planned | Next |
| Cron templates | ⬜ Planned | Next |
| Alert → chat routing | ⬜ Planned | Next |
| Agent discovery (MCP/OpenAPI) | ⬜ Planned | Future |
| Multi-agent coordination | ⬜ Planned | Future |

---

*The engine is ready. The interface layer is next.*
