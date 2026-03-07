---
name: b1e55ed-research
description: Deep research on a single token producing a structured conviction signal. Use when asked to research a specific token, analyze a crypto asset in depth, or generate a research signal. Triggers on "research {TOKEN}", "deep dive {TOKEN}", "analyze {TOKEN}", or any request for comprehensive token analysis. Requires b1e55ed MCP tools for regime context, existing signals, and signal submission.
---

# b1e55ed Token Research Skill

## Overview

<!-- Shannon: information is the resolution of uncertainty.
     Four sources. One signal. The research is not the reading — it is the compression. -->
Conducts deep, multi-source research on a single token and produces a structured conviction signal submitted to the b1e55ed signal pipeline. Combines regime context, on-chain signals, social signals, and web research into a comprehensive analysis with institutional-grade output.

## Prerequisites

- **b1e55ed MCP tools** configured in `extensions_config.json`:
  - `list_producers` + `get_latest_signal("regime_detector")` — current market regime
  - `list_producers` + `get_latest_signal` per producer — filtered signal retrieval
  - `get_latest_signal` (read-only; signal submission via REST API) — signal emission
- **operator_node_id** — your forge node ID (find via `b1e55ed identity show`)
- **Memory keys** (optional, for delta analysis):
  - `{TOKEN}_last_regime` — regime at last research
  - `{TOKEN}_last_conviction` — prior conviction score
  - `{TOKEN}_key_findings` — prior key findings summary
  - `{TOKEN}_last_researched` — ISO timestamp of last research

## Model Guidance

| Step | Model Recommendation |
|------|---------------------|
| Coordinator | Strong model (Claude Sonnet or equivalent) |
| Web search steps (4-6) | Any model (cost-efficient) |
| Synthesis step (7-9) | Strong model (Claude Sonnet or equivalent) |

## Workflow

### Step 1: Read Prior Memory

Before starting research, check memory for prior context on this token:

- Read `{TOKEN}_last_regime` — what was the regime last time?
- Read `{TOKEN}_last_conviction` — what was the prior conviction score?
- Read `{TOKEN}_key_findings` — what were the key findings last time?
- Read `{TOKEN}_last_researched` — when was the last research run?

If no prior memory exists, this is a first-time research. Note that in the output.

### Step 2: Get Regime Context

Call `list_producers` + `get_latest_signal("regime_detector")` to retrieve:
- Current regime classification (risk-on, risk-off, neutral, etc.)
- Kill switch status
- Trend direction

Store the full response — this frames all subsequent analysis.

### Step 3: Retrieve Existing On-Chain Signals

Call `list_producers` + `get_latest_signal` per producer with parameters:
- `domain`: `onchain`
- `symbol`: `{TOKEN}`

Record: signal count, latest signal timestamp, dominant signal direction, any whale activity signals.

### Step 4: Retrieve Existing Social Signals

Call `list_producers` + `get_latest_signal` per producer with parameters:
- `domain`: `social`
- `symbol`: `{TOKEN}`

Record: sentiment distribution, notable social spikes, influencer mentions.

### Step 5: Web Research — Price Action & CT Sentiment

Search the web for recent price action and crypto Twitter sentiment:

```
"{TOKEN} price action site:twitter.com last 24h"
```

Extract: key narratives, notable calls (bullish/bearish), engagement levels on {TOKEN} posts.

### Step 6: Web Research — Fundamentals & News

Search the web for fundamental developments:

```
"{TOKEN} fundamentals news {CURRENT_YEAR}"
```

Extract: protocol updates, partnerships, governance proposals, team changes, TVL movements.

### Step 7: Web Research — On-Chain Whale Activity

Search the web for whale and smart money activity:

```
"{TOKEN} on-chain whale activity"
```

Extract: large transfers, accumulation/distribution patterns, exchange inflows/outflows.

### Step 8: Synthesize Findings

Compare current findings to prior memory for this token:

1. **Delta analysis**: What changed since last research? (Skip if no prior memory.)
2. **Signal alignment**: Do on-chain, social, and web research signals agree or conflict?
3. **Regime fit**: Does the token thesis align with the current regime?
4. **Conviction assessment**: Weight evidence for and against a directional view.

### Step 9: Determine Signal Classification

Synthesis output:

| Condition | Signal Class |
|-----------|-------------|
| No clear directional thesis | `observation` |
| Directional thesis with supporting evidence | `conviction` |
| Strong multi-source confirmation | `conviction` (high confidence) |

### Step 10: Submit Research Signal

Call `get_latest_signal` (read-only; signal submission via REST API) with all required fields:

```json
{
  "operator_node_id": "{YOUR_FORGE_NODE_ID}",
  "signal_class": "conviction|observation",
  "domain": "research",
  "symbol": "{TOKEN}",
  "direction": "bullish|bearish|neutral",
  "confidence": 0.0-1.0,
  "horizon": "short|medium|long",
  "thesis": "One-sentence thesis statement",
  "evidence": "Key supporting evidence summary",
  "risk_factors": "Key risks that could invalidate thesis",
  "sources": ["on-chain", "social", "web-research"]
}
```

### Step 11: Write HTML Artifact

Write a structured HTML report to the sandbox: `research_{TOKEN}_{YYYY-MM-DD}.html`

The artifact must include these sections:

```
1. Executive Summary
   - One-paragraph synthesis of findings
   - Direction + conviction score

2. Regime Context
   - Current regime status
   - How regime affects this token's outlook

3. On-Chain Signals
   - Signal summary from b1e55ed pipeline
   - Whale activity from web research

4. Social Signals
   - Sentiment distribution
   - Notable CT narratives

5. Web Research Findings
   - Fundamental developments
   - News and catalysts

6. Delta from Prior Research
   - What changed since last research (or "First research — no prior data")
   - Conviction change direction and magnitude

7. Conviction Score
   - Numeric score (0-10)
   - Breakdown by dimension: narrative, on-chain, technical, risk

8. Risk Factors
   - Top 3-5 risks that could invalidate the thesis
   - Invalidation conditions (specific, measurable)
```

Style the HTML with dark mode CSS:
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

### Step 12: Persist to Memory

Write the following memory keys:

| Key | Value |
|-----|-------|
| `{TOKEN}_last_regime` | Current regime classification |
| `{TOKEN}_last_conviction` | Numeric conviction score (0-10) |
| `{TOKEN}_key_findings` | Brief summary of key findings (max 200 words) |
| `{TOKEN}_last_researched` | Current ISO timestamp |

## Error Handling

| Failure | Action |
|---------|--------|
| `get_latest_signal` (read-only; signal submission via REST API) fails | Log error. Still write HTML artifact. Add "⚠️ Signal submission failed" banner to artifact. |
| `list_producers` + `get_latest_signal("regime_detector")` fails | Retry once. If still fails, note "Regime data unavailable" in artifact and proceed without regime context. |
| `list_producers` + `get_latest_signal` per producer fails | Retry once. If still fails, note which signal domain is missing in the artifact. Proceed with available data. |
| Web search returns no results | Try alternative query phrasing. If still empty, note the gap explicitly in the relevant artifact section. |
| Memory read fails | Treat as first-time research. Skip delta section or note "No prior data available." |

**Critical rule:** Never silently skip a failed step. Every gap must be noted in the output artifact.

### Model-Level Failures

Model failure during coordinator steps (timeout, context overflow, provider error) is **intentionally not handled in this skill file**. This is a design decision, not an omission.

DeerFlow's coordinator layer owns model-level retry and fallback — it retries failed steps, routes to backup models, and surfaces unrecoverable failures to the operator. Defining fallback model behavior inside a skill file would duplicate that logic and couple the skill to a specific deployment configuration, breaking portability across DeerFlow instances with different model configurations.

**What this skill owns:** tool call failures, data gaps, partial artifacts.
**What DeerFlow's coordinator owns:** model retries, context management, step-level recovery.

This follows DeerFlow's skill authoring best practice: skills define *what to do*, the coordinator defines *how to recover when the doing fails*.

## Output

1. **Structured JSON signal** — emitted via `get_latest_signal` (read-only; signal submission via REST API) to the b1e55ed pipeline
2. **HTML artifact** — `research_{TOKEN}_{YYYY-MM-DD}.html` written to sandbox
3. **Memory updates** — four keys persisted for delta analysis on next run
