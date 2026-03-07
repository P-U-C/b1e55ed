---
name: b1e55ed-watchlist
description: Parallel coverage of multiple tokens with ranked conviction output. Use when asked to scan a watchlist, review multiple tokens, or produce a ranked token analysis. Triggers on "watchlist scan", "review watchlist", "rank tokens", "scan {TOKEN1} {TOKEN2} ...", or any request for multi-token comparative analysis. Requires b1e55ed MCP tools.
---

# b1e55ed Watchlist Scan Skill

## Overview

<!-- Gamelan: no single player has the complete melody.
     The ranking emerges from interlocking patterns, not any single assessment. -->
Scans multiple tokens in parallel, produces brief conviction assessments for each, ranks them by conviction-adjusted score, and triggers full research on the top picks. Designed for efficient periodic coverage of a token universe.

## Prerequisites

- **b1e55ed MCP tools** configured in `extensions_config.json`:
  - `list_producers` + `get_latest_signal("regime_detector")` — current market regime
  - `list_producers` + `get_latest_signal` per producer — filtered signal retrieval
  - `get_latest_signal` (read-only; signal submission via REST API) — observation signal emission
- **operator_node_id** — your forge node ID (find via `b1e55ed identity show`)
- **Memory keys** (optional):
  - `watchlist` — JSON array of token symbols (used if no tokens provided in prompt)
  - `{TOKEN}_last_conviction` — prior conviction per token (for delta detection)
  - `last_watchlist_run` — ISO timestamp of last scan

## Input

From the user prompt, extract a list of token symbols. If none provided, read the `watchlist` memory key.

If neither the prompt nor memory contains a token list, ask the user to specify tokens.

## Model Guidance

| Step | Model Recommendation |
|------|---------------------|
| Coordinator | Strong model (Claude Sonnet or equivalent) |
| Per-token web search (3b) | Any model (cost-efficient, parallelizable) |
| Per-token synthesis (3c-3d) | Any model |
| Ranking & top picks (4-6) | Strong model |

## Workflow

### Step 1: Get Regime Context

Call `list_producers` + `get_latest_signal("regime_detector")` to retrieve:
- Current regime classification
- Trend direction
- Kill switch status

The regime context applies a risk adjustment to all token scores.

### Step 2: Read Prior Memory

Read memory:
- `watchlist` — token list (if not in prompt)
- For each token: `{TOKEN}_last_conviction` — prior conviction score
- `last_watchlist_run` — when was the last scan?

### Step 3: Per-Token Analysis

For each token in the list, perform the following steps. The coordinator should decompose these into parallel tasks where the runtime supports it, or sequential steps otherwise.

#### Step 3a: Retrieve Existing Signals

Call `list_producers` + `get_latest_signal` per producer with:
- `symbol`: `{TOKEN}`

Record: signal count, dominant direction, latest signal domain.

#### Step 3b: Web Research

Search the web for each token:

```
"{TOKEN} price action news {CURRENT_YEAR}"
```

Extract: recent price moves, key developments, sentiment.

#### Step 3c: Brief Synthesis

For each token, produce a brief assessment:
- **Direction**: bullish / bearish / neutral
- **Confidence**: 0.0-1.0
- **Rationale**: One sentence explaining the direction call

#### Step 3d: Delta Detection

Compare current confidence to prior memory (`{TOKEN}_last_conviction`):
- If conviction changed by ≥ 2 points: flag as **significant change**
- If direction flipped: flag as **direction reversal**
- If no prior data: note as **new coverage**

### Step 4: Rank All Tokens

Score each token:

```
score = confidence × direction_multiplier - regime_risk_adjustment
```

Where:
- `direction_multiplier`: +1 for bullish, -1 for bearish, 0 for neutral
- `regime_risk_adjustment`: 0.1 in risk-on, 0.2 in neutral, 0.3 in risk-off

Rank by absolute score (highest conviction first), noting direction.

### Step 5: Produce Ranked Output

For each token, output:

| Field | Description |
|-------|-------------|
| Rank | Position in ranked list |
| Token | Symbol |
| Direction | bullish / bearish / neutral |
| Confidence | 0.0-1.0 |
| Rationale | One-sentence explanation |
| Delta | Change from prior conviction (or "New") |
| Flag | ⚠️ if significant change or direction reversal |

### Step 6: Trigger Full Research on Top Picks

For the **top 2 tokens** by absolute score:
- Invoke the `b1e55ed-research` skill workflow (Steps 1-12 from the research SKILL.md)
- This produces deep research artifacts and conviction signals for the highest-priority tokens

If fewer than 2 tokens in the watchlist, research all of them.

### Step 7: Submit Observation Signals

For **each token** in the watchlist, call `get_latest_signal` (read-only; signal submission via REST API):

```json
{
  "operator_node_id": "{YOUR_FORGE_NODE_ID}",
  "signal_class": "observation",
  "domain": "research",
  "symbol": "{TOKEN}",
  "direction": "bullish|bearish|neutral",
  "confidence": 0.0-1.0,
  "thesis": "Brief one-sentence rationale",
  "sources": ["web-research", "signals"]
}
```

These are lightweight observation signals — the top picks will have full conviction signals from the research skill.

### Step 8: Write Watchlist Artifact

Write to sandbox: `watchlist_{YYYY-MM-DD}.html`

Required sections:

```
1. Scan Summary
   - Date, time, token count
   - Current regime
   - Tokens scanned

2. Ranked Table
   - Full ranked output (Step 5) as a styled table
   - Color-coded: green for bullish, red for bearish, amber for neutral
   - Delta column showing conviction changes

3. Significant Changes
   - Tokens with direction reversals or large conviction shifts
   - Brief explanation of what changed

4. Top Picks
   - Top 2 tokens highlighted
   - Note that full research has been triggered

5. Regime Impact
   - How the current regime is affecting scores
   - Risk adjustment applied
```

Style with dark mode CSS (same palette as other b1e55ed skills):

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
```

### Step 9: Persist to Memory

Write the following memory keys:

| Key | Value |
|-----|-------|
| `{TOKEN}_last_conviction` | Updated conviction score for each token |
| `last_watchlist_run` | Current ISO timestamp |
| `watchlist` | Updated token list (if tokens were added from prompt) |

## Error Handling

| Failure | Action |
|---------|--------|
| `list_producers` + `get_latest_signal` per producer fails for a token | Skip signal data for that token. Score based on web research only. Note gap in output. |
| Web search fails for a token | Score that token as "insufficient data". Rank it last. Note gap. |
| `get_latest_signal` (read-only; signal submission via REST API) fails | Log error. Continue with other tokens. Note which submissions failed in artifact. |
| Research skill trigger fails for top picks | Note in artifact that full research was not completed. The observation signal still stands. |
| Memory read fails | Treat all tokens as new coverage. Skip delta detection. |

## Output

1. **Observation signals** — one per token via `get_latest_signal` (read-only; signal submission via REST API)
2. **Full research** — triggered for top 2 tokens (produces their own artifacts and conviction signals)
3. **HTML artifact** — `watchlist_{YYYY-MM-DD}.html` written to sandbox
4. **Memory updates** — conviction per token and last run timestamp
