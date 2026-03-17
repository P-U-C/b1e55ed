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


## Current MCP API

b1e55ed ships two MCP interfaces:

### 1. REST JSON-RPC endpoint — `POST /mcp` (recommended for DeerFlow)

The primary MCP interface. Available when the API server is running (`b1e55ed start`, port 8000 by default). Implements JSON-RPC 2.0 with full tool suite:

| Tool | Description |
|------|-------------|
| `get_regime_status` | Current regime, kill switch level, last cycle timestamp, trend indicator |
| `get_top_signals` | Recent signals with domain/symbol/signal_class filter and cursor pagination |
| `get_regime_history` | Regime change history for last N days with stability indicator |
| `get_open_positions` | All currently open positions from the OMS |
| `submit_research_signal` | Validate and emit a `signal.research.v1` event (requires `operator_node_id`) |
| `get_signals_bulk_export` | Bulk historical signal export for backtest use (up to 1000/call) |
| `get_signal_attribution` | Attribution metadata for a signal by event ID |
| `b1e55ed_provenance_check` | Chain-verified producer lineage before acting on a signal |
| `get_brain_status` | Brain status: regime, kill switch level, last cycle info |
| `get_recent_signals` | Recent brain signals from the event store (domain-filterable) |
| `emit_producer_signal` | Inject a signal into the ingestion bus on behalf of a registered producer |

Call `tools/list` to enumerate live tools with full schemas.

### 2. FastMCP standalone server — port 7337 (producer registry)

A lightweight producer registry server started alongside the API. Exposes 3 tools over SSE transport:

| Tool | Description |
|------|-------------|
| `list_producers()` | Returns all registered producers with latest signal state |
| `get_latest_signal(producer_name)` | Returns the most recent signal from a specific producer |
| `get_signal_history(producer_name, limit=10)` | Returns signal history for a producer |

**Producer names** (use as `producer_name`): `regime_detector`, `onchain_scanner`, `social_intel`, `curator`, and others — call `list_producers()` to enumerate.

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
      "transport": "http",
      "url": "http://localhost:8000/mcp",
      "headers": {
        "X-API-Key": "<your-b1e55ed-api-token>"
      },
      "tools": [
        "get_regime_status",
        "get_top_signals",
        "get_regime_history",
        "get_open_positions",
        "submit_research_signal",
        "get_signals_bulk_export",
        "get_signal_attribution",
        "b1e55ed_provenance_check",
        "get_brain_status",
        "get_recent_signals",
        "emit_producer_signal"
      ]
    }
  }
}
```

The API token is in your `config/b1e55ed.yaml` under `api.auth_token`, or set via `B1E55ED_API_TOKEN` env var.

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
