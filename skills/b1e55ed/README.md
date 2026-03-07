# b1e55ed Skill Pack for DeerFlow

Institutional-grade crypto research and analysis skills for [DeerFlow](https://github.com/bytedance/deer-flow), powered by the b1e55ed signal pipeline.

## Skills

| Skill | Purpose | Trigger Examples |
|-------|---------|-----------------|
| **research** | Deep single-token research → structured conviction signal | "research SOL", "deep dive ETH", "analyze HYPE" |
| **brief** | Daily IC brief — morning report with regime, signals, portfolio | "daily brief", "morning report", "IC brief" |
| **thesis** | Structured thesis evaluation with multi-dimensional scoring | "evaluate thesis: SOL will outperform due to AI agents" |
| **watchlist** | Parallel multi-token scan → ranked conviction output | "scan watchlist", "rank SOL ETH HYPE BTC" |
| **backtest** | Natural language strategy → sandbox backtest → formatted report | "backtest momentum on SOL 90 days" |

## Installation

### Option 1: Copy to DeerFlow Skills Directory

```bash
# Copy the entire b1e55ed skill directory to DeerFlow's custom skills path
cp -r skills/b1e55ed/ /path/to/deer-flow/skills/custom/b1e55ed/
```

### Option 2: Mount as Volume (Docker)

```yaml
# docker-compose.yml
volumes:
  - ./skills/b1e55ed:/mnt/skills/custom/b1e55ed:ro
```

### Option 3: Symlink

```bash
ln -s /path/to/b1e55ed/skills/b1e55ed /path/to/deer-flow/skills/custom/b1e55ed
```

## Required MCP Configuration

Add the b1e55ed MCP server to DeerFlow's `extensions_config.json`:

```json
{
  "extensions": {
    "b1e55ed": {
      "type": "mcp",
      "transport": "stdio",
      "command": "python",
      "args": ["-m", "b1e55ed.mcp.server"],
      "env": {
        "B1E55ED_API_URL": "http://localhost:8000",
        "B1E55ED_OPERATOR_NODE_ID": "<your-forge-node-id>"
      },
      "tools": [
        "get_regime_status",
        "get_top_signals",
        "get_regime_history",
        "get_open_positions",
        "submit_research_signal",
        "get_signals_bulk_export",
        "get_signal_attribution",
        "b1e55ed_provenance_check"
      ]
    }
  }
}
```

## Finding Your Operator Node ID

The `operator_node_id` is required for `submit_research_signal`. To find yours:

```bash
b1e55ed identity show
```

This prints your forge node ID. Set it in:
1. The `extensions_config.json` as `B1E55ED_OPERATOR_NODE_ID` env var
2. Or as a DeerFlow memory key: `operator_node_id`

## Required Memory Keys

Skills use DeerFlow's memory system for state persistence and delta analysis. Initialize these keys before first use (or let skills populate them on first run):

### Research Skill
| Key | Type | Description |
|-----|------|-------------|
| `{TOKEN}_last_regime` | string | Regime at last research for this token |
| `{TOKEN}_last_conviction` | number | Prior conviction score (0-10) |
| `{TOKEN}_key_findings` | string | Summary of prior findings (max 200 words) |
| `{TOKEN}_last_researched` | string | ISO timestamp of last research |

### Brief Skill
| Key | Type | Description |
|-----|------|-------------|
| `brief_last_summary` | string | Prior brief summary (2-3 sentences) |
| `brief_last_regime` | string | Regime at last brief |
| `brief_action_items` | JSON array | Pending action items |

### Watchlist Skill
| Key | Type | Description |
|-----|------|-------------|
| `watchlist` | JSON array | Token symbols to scan (e.g., `["SOL", "ETH", "HYPE"]`) |
| `{TOKEN}_last_conviction` | number | Shared with research skill |
| `last_watchlist_run` | string | ISO timestamp of last scan |

### Backtest Skill
No persistent memory keys required. All state is contained in output artifacts.

## Model Recommendations

| Skill | Coordinator | Worker Steps | Synthesis |
|-------|------------|--------------|-----------|
| research | Claude Sonnet+ | Any | Claude Sonnet+ |
| brief | Claude Sonnet+ | Any | Claude Sonnet+ |
| thesis | Claude Sonnet+ | Any | Claude Sonnet+ |
| watchlist | Claude Sonnet+ | Any (parallel) | Claude Sonnet+ |
| backtest | Claude Sonnet+ | N/A | Any |

"Any" = cost-efficient model for web search and data retrieval steps.
"Claude Sonnet+" = Claude Sonnet 4 or equivalent strong reasoning model.

## Output Artifacts

All skills produce HTML artifacts written to the DeerFlow sandbox with consistent dark-mode styling:

```
research_{TOKEN}_{YYYY-MM-DD}.html    — Deep research report
brief_{YYYY-MM-DD}.html               — Daily IC brief
thesis_{TOKEN}_{YYYY-MM-DD}.html      — Thesis evaluation
watchlist_{YYYY-MM-DD}.html           — Ranked watchlist scan
backtest_{ASSET}_{YYYY-MM-DD}.html    — Backtest report
backtest_{ASSET}_{YYYY-MM-DD}.py      — Generated backtest script
```

## MCP Tools Reference

| Tool | Description | Used By |
|------|-------------|---------|
| `get_regime_status` | Current regime, kill switch, trend | research, brief, thesis, watchlist |
| `get_top_signals` | Domain/symbol filtered signals, paginated | research, brief, thesis, watchlist |
| `get_regime_history` | 7-day regime trend | (available, not currently used) |
| `get_open_positions` | Live portfolio with P&L | brief |
| `submit_research_signal` | Emit signal.research.v1 event | research, thesis, watchlist |
| `get_signals_bulk_export` | Historical signal data for backtest | backtest |
| `get_signal_attribution` | Signal provenance chain | (available, not currently used) |
| `b1e55ed_provenance_check` | Chain verification | (available, not currently used) |

## Data Source Disclaimer

Backtest results use b1e55ed signal history, not raw market price data. Strategies simulate signal-based entries and exits. Results indicate signal quality and timing correlation, not direct P&L from market execution. No slippage, fees, or execution risk is modeled.
