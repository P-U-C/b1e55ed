---
name: b1e55ed-brief
description: Daily investment committee brief — institutional-grade morning report synthesizing regime, signals, portfolio, and market context. Use when asked for "daily brief", "morning report", "IC brief", "market summary", or any request for a comprehensive portfolio and market overview. Requires b1e55ed MCP tools.
---

# b1e55ed Daily IC Brief Skill

## Overview

Produces an institutional-grade daily investment committee brief combining regime status, top signals, live portfolio, and market context. Designed for daily consumption — concise, actionable, delta-focused.

## Prerequisites

- **b1e55ed MCP tools** configured in `extensions_config.json`:
  - `get_regime_status` — current market regime
  - `get_top_signals` — signal retrieval
  - `get_open_positions` — live portfolio
- **Memory keys** (optional, for delta analysis):
  - `brief_last_summary` — prior brief summary
  - `brief_last_regime` — regime at last brief
  - `brief_action_items` — pending action items from prior brief

## Model Guidance

| Step | Model Recommendation |
|------|---------------------|
| Coordinator | Strong model (Claude Sonnet or equivalent) |
| Web search steps (4-5) | Any model (cost-efficient) |
| Synthesis step (7-8) | Strong model (Claude Sonnet or equivalent) |

## Workflow

### Step 1: Get Regime Status

Call `get_regime_status` to retrieve:
- Current regime classification
- Kill switch status
- Trend direction and strength

This is the framing context for the entire brief.

### Step 2: Get Top Signals

Call `get_top_signals` with parameters:
- No domain filter (all domains)
- `limit`: `10`

Record the top 10 signals across all domains — these represent the system's current highest-priority intelligence.

### Step 3: Get Open Positions

Call `get_open_positions` to retrieve:
- All live positions with current P&L
- Entry prices and current prices
- Position sizes and directions

### Step 4: Web Research — Market Context

Search the web for broad crypto market context:

```
"crypto market news today {CURRENT_YEAR}"
```

Extract: major market moves, regulatory news, macro events affecting crypto.

### Step 5: Web Research — Portfolio Token News

For the top 3 tokens by position size from open positions, search:

```
"{TOKEN} news today"
```

Extract: token-specific developments, catalysts, risks.

### Step 6: Read Prior Brief Memory

Check memory for delta analysis:
- `brief_last_summary` — what was the prior brief's key message?
- `brief_last_regime` — has regime changed?
- `brief_action_items` — were prior action items addressed?

### Step 7: Synthesize

Combine all data sources into a coherent brief:

1. **What changed since yesterday** — regime shifts, new signals, position P&L changes
2. **What warrants attention** — signals that diverge from positions, regime changes, large P&L moves
3. **Action items** — specific, actionable recommendations

### Step 8: Write HTML Brief

Write a polished HTML brief to the sandbox: `brief_{YYYY-MM-DD}.html`

Required sections:

```
1. Regime Overview
   - Current regime + trend
   - Change from prior brief (if any)
   - Kill switch status

2. Market Context
   - Broad crypto market summary
   - Key macro/regulatory events
   - Market sentiment assessment

3. Portfolio Status
   - Position table: token, direction, entry, current, P&L%, size
   - Total portfolio P&L
   - Positions requiring attention (large drawdowns, target proximity)

4. Top Signals
   - Table of top 10 signals: domain, symbol, direction, confidence, timestamp
   - Notable signal clusters or divergences

5. Key Changes
   - Delta from prior brief
   - New signals not in prior brief
   - Regime changes
   - Position P&L movements

6. Action Items
   - Specific, actionable items (max 5)
   - Priority: high/medium/low
   - Examples: "Review SOL position — signal divergence", "Consider taking profit on X — target proximity"
```

Style with dark mode CSS:

```css
:root {
  --bg: #0a0a0a;
  --text: #e0e0e0;
  --green: #00d084;
  --red: #ff4444;
  --amber: #ffaa00;
  --surface: #1a1a1a;
  --border: #333;
}
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  max-width: 900px;
  margin: 0 auto;
  padding: 2rem;
  line-height: 1.6;
}
table {
  width: 100%;
  border-collapse: collapse;
  margin: 1rem 0;
}
th, td {
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--border);
  text-align: left;
}
th { color: var(--amber); font-weight: 600; }
.positive { color: var(--green); }
.negative { color: var(--red); }
.warning { color: var(--amber); }
h1, h2, h3 { color: #fff; }
```

### Step 9: Persist to Memory

Write the following memory keys:

| Key | Value |
|-----|-------|
| `brief_last_summary` | 2-3 sentence summary of this brief's key message |
| `brief_last_regime` | Current regime classification |
| `brief_action_items` | JSON array of action items from this brief |

## Error Handling

| Failure | Action |
|---------|--------|
| `get_open_positions` fails | Produce brief WITHOUT portfolio section. Add "⚠️ Portfolio data unavailable" note. Continue with all other sections. |
| `get_regime_status` fails | Retry once. If still fails, note "Regime data unavailable" and produce brief with market context only. |
| `get_top_signals` fails | Retry once. If still fails, note "Signal data unavailable" in Top Signals section. |
| Web search fails | Try alternative queries. Note any gaps in Market Context section. |
| Memory read fails | Skip delta analysis. Note "No prior brief for comparison" in Key Changes section. |

## Output

1. **HTML artifact** — `brief_{YYYY-MM-DD}.html` written to sandbox
2. **Memory updates** — three keys persisted for next brief's delta analysis
