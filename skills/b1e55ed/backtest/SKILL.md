---
name: b1e55ed-backtest
description: Natural language strategy description to sandbox backtest with formatted report. Use when asked to backtest a strategy, simulate trades, test a hypothesis against historical data, or evaluate a trading approach. Triggers on "backtest {STRATEGY}", "simulate {STRATEGY}", "test strategy", or any request to evaluate historical performance of a signal-based approach. Requires b1e55ed MCP tools.
---

# b1e55ed Backtest Skill

## Overview

Converts a natural language strategy description into a Python backtest script, executes it against b1e55ed historical signal data, and produces a formatted report with risk metrics and equity curve visualization. Signal-based backtesting — not price-based.

<!-- Popper: a theory that explains everything explains nothing.
     The backtest is not the trade. The map is not the territory.
     But a map that has never been checked against territory is not a map — it is a wish. -->

## Prerequisites

- **b1e55ed MCP tools** configured in `extensions_config.json`:
  - `get_signal_history(producer_name, limit=90)` — historical signal data
- **Sandbox Python environment** with:
  - `json`, `datetime`, `statistics` (stdlib)
  - `matplotlib` (for chart generation)

## Input

From the user prompt, extract strategy description in natural language. Examples:
- "Momentum strategy on SOL, 90 days"
- "Buy when on-chain signals are bullish and social is neutral, sell when both flip bearish"
- "Follow whale signals on ETH, medium confidence threshold"

## Model Guidance

| Step | Model Recommendation |
|------|---------------------|
| Coordinator | Strong model (Claude Sonnet or equivalent) |
| Strategy parsing (1) | Strong model |
| Script generation (3) | Strong model (needs coding ability) |
| Report writing (6) | Any model |

## Workflow

### Step 1: Parse Strategy Description

Extract strategy parameters from natural language:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `asset` | Token symbol | Required (no default) |
| `lookback_days` | Historical window in days | 90 |
| `strategy_type` | Category: momentum, mean-reversion, signal-following, multi-factor | Infer from description |
| `entry_conditions` | When to enter a position | Infer from description |
| `exit_conditions` | When to exit a position | Infer from description |
| `confidence_threshold` | Minimum signal confidence to act on | 0.5 |
| `domain_filter` | Which signal domains to use | All domains |

If critical parameters are ambiguous, make reasonable assumptions and document them in the report.

### Step 2: Export Historical Signals

Call `get_signal_history(producer_name, limit=90)` with:
- `domain`: `{domain_filter}` (or omit for all domains)
- `symbol`: `{ASSET}`
- `from_ts`: `{lookback_days ago as ISO timestamp}`

Record: total signal count, date range covered, domain distribution.

**Minimum data check:** If fewer than 10 signals are returned, note the limitation and produce a partial analysis with available data.

### Step 3: Generate Python Backtest Script

Write a Python backtest script to the sandbox: `backtest_{ASSET}_{YYYY-MM-DD}.py`

The script must:

```python
#!/usr/bin/env python3
"""
b1e55ed Signal Backtest: {STRATEGY_DESCRIPTION}
Asset: {ASSET}
Lookback: {LOOKBACK_DAYS} days
Generated: {YYYY-MM-DD}

DATA SOURCE NOTE:
This backtest uses b1e55ed signal history, not raw price data.
Strategy simulates signal-based entries/exits, not price-based.
"""

import json
import sys
from datetime import datetime
from statistics import mean, stdev

# --- Configuration ---
SIGNAL_DATA_PATH = "signals_{ASSET}.json"  # Exported signal data
CONFIDENCE_THRESHOLD = {confidence_threshold}
INITIAL_CAPITAL = 10000.0

# --- Load signals ---
def load_signals(path):
    with open(path) as f:
        signals = json.load(f)
    # Sort by timestamp
    signals.sort(key=lambda s: s.get("timestamp", s.get("created_at", "")))
    return signals

# --- Strategy Logic ---
def evaluate_entry(signal, position_open):
    """Return True if this signal triggers an entry."""
    if position_open:
        return False
    # {ENTRY_CONDITIONS implemented here}
    pass

def evaluate_exit(signal, position_open, entry_signal):
    """Return True if this signal triggers an exit."""
    if not position_open:
        return False
    # {EXIT_CONDITIONS implemented here}
    pass

# --- Backtest Engine ---
def run_backtest(signals):
    trades = []
    equity_curve = [INITIAL_CAPITAL]
    capital = INITIAL_CAPITAL
    position_open = False
    entry_signal = None

    for signal in signals:
        confidence = signal.get("confidence", 0)
        if confidence < CONFIDENCE_THRESHOLD:
            continue

        if evaluate_entry(signal, position_open):
            position_open = True
            entry_signal = signal
        elif evaluate_exit(signal, position_open, entry_signal):
            # Calculate simulated return based on signal confidence delta
            entry_conf = entry_signal.get("confidence", 0.5)
            exit_conf = signal.get("confidence", 0.5)
            direction = 1 if entry_signal.get("direction") == "bullish" else -1
            simulated_return = direction * (exit_conf - entry_conf) * 0.1
            
            capital *= (1 + simulated_return)
            equity_curve.append(capital)
            trades.append({
                "entry_ts": entry_signal.get("timestamp"),
                "exit_ts": signal.get("timestamp"),
                "direction": entry_signal.get("direction"),
                "entry_confidence": entry_conf,
                "exit_confidence": exit_conf,
                "return_pct": simulated_return * 100,
                "capital_after": capital
            })
            position_open = False
            entry_signal = None

    return trades, equity_curve

# --- Metrics ---
def calculate_metrics(trades, equity_curve):
    if not trades:
        return {"error": "No trades generated"}
    
    returns = [t["return_pct"] / 100 for t in trades]
    winning = [r for r in returns if r > 0]
    losing = [r for r in returns if r <= 0]
    
    total_return = (equity_curve[-1] / equity_curve[0] - 1) * 100
    
    # Max drawdown
    peak = equity_curve[0]
    max_dd = 0
    for val in equity_curve:
        if val > peak:
            peak = val
        dd = (peak - val) / peak
        if dd > max_dd:
            max_dd = dd
    
    # Sharpe (annualized, assuming daily)
    avg_ret = mean(returns) if returns else 0
    std_ret = stdev(returns) if len(returns) > 1 else 0
    sharpe = (avg_ret / std_ret * (252 ** 0.5)) if std_ret > 0 else 0
    
    return {
        "total_return_pct": round(total_return, 2),
        "trade_count": len(trades),
        "win_rate_pct": round(len(winning) / len(trades) * 100, 1),
        "avg_win_pct": round(mean(winning) * 100, 2) if winning else 0,
        "avg_loss_pct": round(mean(losing) * 100, 2) if losing else 0,
        "max_drawdown_pct": round(max_dd * 100, 2),
        "sharpe_ratio": round(sharpe, 2),
        "profit_factor": round(
            abs(sum(winning) / sum(losing)) if losing and sum(losing) != 0 else float('inf'), 2
        ),
        "avg_hold_signals": round(
            mean([
                # Approximate hold duration by signal count between entry and exit
                1  # Placeholder — would need signal index tracking
            ]), 1
        )
    }

# --- Main ---
if __name__ == "__main__":
    signals = load_signals(SIGNAL_DATA_PATH)
    print(f"Loaded {len(signals)} signals")
    
    trades, equity_curve = run_backtest(signals)
    metrics = calculate_metrics(trades, equity_curve)
    
    # Write results
    results = {
        "strategy": "{STRATEGY_DESCRIPTION}",
        "asset": "{ASSET}",
        "lookback_days": {LOOKBACK_DAYS},
        "signal_count": len(signals),
        "metrics": metrics,
        "trades": trades,
        "equity_curve": equity_curve
    }
    
    with open("backtest_results_{ASSET}.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    # Generate equity curve chart
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(equity_curve, color="#00d084", linewidth=1.5)
        ax.fill_between(range(len(equity_curve)), equity_curve, equity_curve[0],
                        where=[v >= equity_curve[0] for v in equity_curve],
                        alpha=0.15, color="#00d084")
        ax.fill_between(range(len(equity_curve)), equity_curve, equity_curve[0],
                        where=[v < equity_curve[0] for v in equity_curve],
                        alpha=0.15, color="#ff4444")
        ax.set_facecolor("#0a0a0a")
        fig.patch.set_facecolor("#0a0a0a")
        ax.tick_params(colors="#e0e0e0")
        ax.set_title(f"Equity Curve — {ASSET} Signal Backtest", color="#e0e0e0")
        ax.set_xlabel("Trade #", color="#e0e0e0")
        ax.set_ylabel("Capital ($)", color="#e0e0e0")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["bottom"].set_color("#333")
        ax.spines["left"].set_color("#333")
        ax.axhline(y=equity_curve[0], color="#ffaa00", linestyle="--", alpha=0.5)
        plt.tight_layout()
        plt.savefig("backtest_chart_{ASSET}.png", dpi=150)
        print("Chart saved: backtest_chart_{ASSET}.png")
    except ImportError:
        print("matplotlib not available — chart skipped")
    
    # Print summary
    print(json.dumps(metrics, indent=2))
```

**Important:** The script template above is a starting point. Adapt the `evaluate_entry` and `evaluate_exit` functions to match the user's described strategy. The coordinator should generate strategy-specific logic based on the parsed parameters from Step 1.

### Step 4: Execute Backtest

Run the script in the DeerFlow sandbox:

```bash
# First, write the exported signal data
# (coordinator writes the bulk export JSON to signals_{ASSET}.json)

# Then execute the backtest
python backtest_{ASSET}_{YYYY-MM-DD}.py
```

### Step 5: Read Results

Read the output files:
- `backtest_results_{ASSET}.json` — metrics and trade log
- `backtest_chart_{ASSET}.png` — equity curve visualization (if generated)

### Step 6: Write Formatted Report

Write to sandbox: `backtest_{ASSET}_{YYYY-MM-DD}.html`

Required sections:

```
1. Strategy Description
   - Natural language description as provided
   - Parsed parameters (asset, lookback, conditions)
   - Assumptions made

2. Parameters
   - Table of all strategy parameters
   - Confidence threshold
   - Signal domains used
   - Lookback period

3. Data Source Note
   - IMPORTANT: "This backtest uses b1e55ed signal history, not price data.
     Strategy simulates signal-based entries/exits. Results indicate signal
     quality and timing, not direct P&L from market execution."

4. Results Summary
   - Key metrics table:
     - Total Return (%)
     - Sharpe Ratio
     - Max Drawdown (%)
     - Win Rate (%)
     - Trade Count
     - Profit Factor
     - Avg Win / Avg Loss

5. Equity Curve
   - Embedded chart image (base64 or linked)
   - If chart not available, note absence

6. Trade Log
   - Table of all trades: entry timestamp, exit timestamp,
     direction, entry confidence, exit confidence, return %
   - Highlight best and worst trades

7. Risk Metrics
   - Max drawdown analysis
   - Longest losing streak
   - Recovery time from max drawdown
   - Concentration risk (if applicable)

8. Limitations
   - Signal-based simulation, not price-based
   - Historical signal quality may differ from future
   - No slippage, fees, or execution risk modeled
   - Sample size limitations (if < 30 trades)
```

Style with dark mode CSS (same palette as other b1e55ed skills).

## Error Handling

| Failure | Action |
|---------|--------|
| `get_signal_history(producer_name, limit=90)` returns < 10 signals | Produce partial report. Note "⚠️ Insufficient data — only {N} signals available. Results are not statistically significant." |
| `get_signal_history(producer_name, limit=90)` fails | Report cannot proceed. Return error message with suggestion to check MCP configuration. |
| Python script execution fails | Read error output. Fix common issues (import errors, data format). Retry once. If still fails, report the error with the script for manual debugging. |
| matplotlib not available | Skip chart generation. Note in report that equity curve visualization is unavailable. |
| No trades generated | Report this explicitly. Suggest adjusting confidence threshold or strategy conditions. |

## Output

1. **Python backtest script** — `backtest_{ASSET}_{YYYY-MM-DD}.py` written to sandbox
2. **Results JSON** — `backtest_results_{ASSET}.json` with metrics and trades
3. **Equity curve chart** — `backtest_chart_{ASSET}.png` (if matplotlib available)
4. **HTML report** — `backtest_{ASSET}_{YYYY-MM-DD}.html` written to sandbox
