---
title: "OpenClaw Integration"
description: "Connect b1e55ed to the OpenClaw AI operator layer."
---

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

**Via CLI:**
```bash
b1e55ed signal "Whale cluster accumulating SOL — 3 wallets, $2M+ in 48h" \
  --symbols SOL --direction bullish --conviction 7
```

**Via API:**
```bash
POST /api/v1/signals/submit
{
  "event_type": "signal.curator.v1",
  "node_id": "your-node-id",
  "source": "operator:telegram",
  "payload": {
    "symbol": "SOL",
    "direction": "bullish",
    "conviction": 7.0,
    "rationale": "Whale cluster accumulating"
  }
}
```

See: [curator.md](curator.md).

### 2. Brain Control (Operator → Engine)

```bash
# Trigger brain cycle
POST /api/v1/brain/run

# Check status
GET /api/v1/brain/status
```

### 3. Alerts (Engine → Operator)

The engine emits alert events. The operator layer decides how to deliver them.

| Alert | Event Type | Urgency |
|-------|-----------|---------|
| Stop hit | `alert.stop_triggered` | Immediate |
| Target reached | `alert.target_hit` | Immediate |
| Kill switch escalation | `alert.kill_switch` | Immediate |
| Regime change | `alert.regime_shift` | Standard |
| Learning loop update | `alert.weights_adjusted` | Low |

Subscribe via SSE stream: `GET /api/v1/events/stream?domain=alert`

### 4. Agent Interfaces

Agents connect via SSE stream or MCP server.

```bash
# Real-time event feed
GET /api/v1/events/stream

# MCP tool calls
POST /api/v1/mcp

# Producer provenance (no auth)
GET /api/v1/oracle/producers/{id}/provenance
```

See: [agent-interfaces.md](agent-interfaces.md).

### 5. Dashboard (Passive Monitoring)

The web dashboard at `localhost:5051` provides real-time visualization. It reads the same event store — no special integration needed.

---

## Component Status

| Component | Status |
|-----------|--------|
| REST API | ✅ Live |
| Dashboard | ✅ Live |
| Event store | ✅ Live |
| Curator endpoint | ✅ Live |
| SSE event stream | ✅ Live (`GET /api/v1/events/stream`) |
| MCP server | ✅ Live (`POST /api/v1/mcp`) |
| Signal attribution | ✅ Live |
| Oracle endpoint | ✅ Live (public, no auth) |
| Provenance check MCP tool | ✅ Live |
| OpenClaw skill package | ⬜ Planned |
| Alert → chat routing | ⬜ Planned |

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

Full conversational loop. Drop alpha, get alerts, control the system through natural language.

### Pattern 3: Multi-Agent

```
Agent A (Research) → Curator API ──┐
Agent B (On-chain) → Curator API ──┤→ Brain → Conviction → Execution
Agent C (Social)   → Curator API ──┘
         Operator  → Control API ──→ Override / Kill Switch
```

Multiple agents feeding signals. One operator with kill switch authority. The compound learning loop benefits from every participant.


## Operator Workspace

If you're running a b1e55ed instance with OpenClaw, use the operator template:

- **GitHub template**: [P-U-C/b1e55ed-operator-template](https://github.com/P-U-C/b1e55ed-operator-template) — fork and fill in 3 files
- **ClawHub skill**: `clawhub install b1e55ed-operator` — auto-installs to your workspace
- **Skills repo**: [P-U-C/openclaw-skills](https://github.com/P-U-C/openclaw-skills)
