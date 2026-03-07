---
name: b1e55ed-thesis
description: Structured thesis evaluation with multi-dimensional scoring and conviction signal. Use when someone shares a trade idea, investment thesis, or asks "what do you think about {TOKEN}" with a specific thesis. Triggers on "evaluate thesis", "thesis {TOKEN}", "is {TOKEN} a good buy because...", or any request to evaluate an investment hypothesis. Requires b1e55ed MCP tools.
---

# b1e55ed Thesis Evaluation Skill

## Overview

Evaluates a specific investment thesis on a token with structured multi-dimensional scoring, produces a conviction signal, and outputs an institutional-grade evaluation artifact. Deliberately steelmans both the bull and bear case.

<!-- Talmudic reasoning: every argument contains its counterargument.
     Two opposing views can both be valid without resolution.
     The steelman is not advocacy. It is epistemology. -->

## Prerequisites

- **b1e55ed MCP tools** configured in `extensions_config.json`:
  - `get_regime_status` — current market regime
  - `get_top_signals` — existing signals for the token
  - `submit_research_signal` — conviction signal emission
- **operator_node_id** — your forge node ID (find via `b1e55ed identity show`)

## Input

From the user prompt, extract:
- **Token symbol** — the asset being evaluated (e.g., SOL, ETH, HYPE)
- **Thesis statement** — the specific investment hypothesis (e.g., "SOL will outperform ETH due to AI agent adoption")

If the thesis statement is vague, ask the user to be specific before proceeding.

## Model Guidance

| Step | Model Recommendation |
|------|---------------------|
| Coordinator | Strong model (Claude Sonnet or equivalent) |
| Web search steps (3-6) | Any model (cost-efficient) |
| Scoring & synthesis (7-10) | Strong model (Claude Sonnet or equivalent) |

## Workflow

### Step 1: Get Regime Context

Call `get_regime_status` to retrieve:
- Current regime classification
- Trend direction
- Kill switch status

Regime context affects thesis viability — a bullish thesis in a risk-off regime needs stronger evidence.

### Step 2: Retrieve Existing Signals

Call `get_top_signals` with parameters:
- `symbol`: `{TOKEN}`
- No domain filter (all domains)

Record: total signal count, domain distribution, dominant direction, latest timestamps.

### Step 3: Web Research — Evidence FOR the Thesis

Search for evidence supporting the thesis:

```
"{TOKEN} {THESIS_KEYWORDS} bullish evidence {CURRENT_YEAR}"
```

Extract: data points, metrics, developments, and expert opinions that support the thesis.

### Step 4: Web Research — Evidence AGAINST the Thesis

Deliberately steelman the bear case:

```
"{TOKEN} {THESIS_KEYWORDS} risks bearish concerns {CURRENT_YEAR}"
```

Extract: counterarguments, risks, historical failures of similar theses, bear case data points.

### Step 5: Web Research — Tokenomics & Supply

Search for token economics and supply dynamics:

```
"{TOKEN} tokenomics unlock schedule vesting {CURRENT_YEAR}"
```

Extract: upcoming unlocks, vesting schedules, inflation rate, supply concentration.

### Step 6: Web Research — Team & Funding

Search for team and ecosystem credibility:

```
"{TOKEN} team background funding investors"
```

Extract: team track record, notable investors, funding rounds, governance structure.

### Step 7: Score Each Dimension

Score each dimension on a 0-10 scale with explicit reasoning:

| Dimension | What It Measures | Score Guidance |
|-----------|-----------------|----------------|
| **Narrative** | Is the thesis aligned with current meta and market narrative? | 0 = counter-narrative, 5 = neutral, 10 = perfectly aligned |
| **On-Chain** | Does on-chain data (signals, whale activity, TVL) support the thesis? | 0 = contradicts, 5 = neutral, 10 = strongly supports |
| **Technical** | Is the price structure aligned with the thesis direction? | 0 = against, 5 = neutral, 10 = confirming |
| **Risk** | What could invalidate the thesis? (higher = MORE risk) | 0 = minimal risk, 5 = moderate, 10 = extreme risk |

For each score, provide 2-3 bullet points of evidence justifying the number.

### Step 8: Derive Overall Conviction

Calculate overall conviction:

```
conviction = (narrative + onchain + technical) / 3 - (risk * 0.3)
```

Clamp result to 0-10 range. Map to confidence for signal submission:
- 0-3: low conviction (confidence: 0.1-0.3)
- 4-6: medium conviction (confidence: 0.4-0.6)
- 7-10: high conviction (confidence: 0.7-1.0)

### Step 9: Determine Horizon

Given thesis nature and evidence:

| Horizon | Timeframe | When to Use |
|---------|-----------|-------------|
| `short` | 1-7 days | Catalyst-driven, event-based thesis |
| `medium` | 7-30 days | Narrative/momentum thesis |
| `long` | 30-90 days | Fundamental/structural thesis |

### Step 10: Submit Conviction Signal

Call `submit_research_signal` with:

```json
{
  "operator_node_id": "{YOUR_FORGE_NODE_ID}",
  "signal_class": "conviction",
  "domain": "research",
  "symbol": "{TOKEN}",
  "direction": "bullish|bearish",
  "confidence": 0.0-1.0,
  "horizon": "short|medium|long",
  "thesis": "{ORIGINAL_THESIS_STATEMENT}",
  "evidence": "Key supporting evidence summary",
  "risk_factors": "Top invalidation risks",
  "scores": {
    "narrative": 0-10,
    "onchain": 0-10,
    "technical": 0-10,
    "risk": 0-10,
    "overall": 0-10
  },
  "sources": ["on-chain", "social", "web-research", "tokenomics"]
}
```

### Step 11: Write Evaluation Artifact

Write to sandbox: `thesis_{TOKEN}_{YYYY-MM-DD}.html`

Required sections:

```
1. Thesis Statement
   - Original thesis as stated
   - Token and direction
   - Proposed horizon

2. Regime Context
   - Current regime and how it affects this thesis
   - Regime-thesis alignment assessment

3. Bull Case Evidence
   - Evidence gathered FOR the thesis
   - Supporting data points and metrics
   - Expert opinions aligned with thesis

4. Bear Case
   - Evidence gathered AGAINST the thesis (steelmanned)
   - Counterarguments and risks
   - Historical analogues that failed

5. Tokenomics & Supply
   - Upcoming unlocks
   - Inflation / dilution risk
   - Supply concentration

6. Score Breakdown
   - Table with each dimension, score (0-10), and justification
   - Overall conviction score with formula shown

7. Verdict
   - Clear direction: BULLISH / BEARISH / NEUTRAL
   - Conviction level: HIGH / MEDIUM / LOW
   - Recommended horizon
   - Position sizing guidance (based on conviction)

8. Invalidation Conditions
   - Specific, measurable conditions that would invalidate the thesis
   - Example: "Thesis invalid if TVL drops below $X" or "Invalid if team announces delay to mainnet"
   - Each condition should be checkable without ambiguity
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

## Error Handling

| Failure | Action |
|---------|--------|
| `submit_research_signal` fails | Log error. Write artifact with "⚠️ Signal submission failed" banner. |
| `get_regime_status` fails | Retry once. If still fails, score without regime context. Note gap in artifact. |
| `get_top_signals` fails | Retry once. If still fails, score on-chain dimension as "N/A — data unavailable". |
| Web search returns no evidence FOR | Note weak bull case. This should lower narrative score. |
| Web search returns no evidence AGAINST | Note absence of bear case evidence. This does NOT mean no risk — flag as potential blind spot. |

## Output

1. **Conviction signal** — emitted via `submit_research_signal` with `signal_class=conviction`
2. **HTML artifact** — `thesis_{TOKEN}_{YYYY-MM-DD}.html` written to sandbox
