# MCP Integration

b1e55ed exposes producer signals over MCP (Model Context Protocol), so AI agents can consume live market intelligence through a standard tool interface.

## What it is

b1e55ed exposes all producer signals via the Model Context Protocol (MCP) — a standard interface that lets AI agents, Claude sessions, and external tools subscribe to live market intelligence without REST API setup.

## Architecture

- Every producer auto-registers with the `MCPProducerRegistry` on startup.
- Signals are pushed to an in-memory ring buffer (last 100 per producer) on every publish cycle.
- The MCP server exposes these as tools: `list_producers`, `get_latest_signal`, `get_signal_history`.
- REST endpoints at `/api/v1/mcp/*` provide HTTP access to the same registry (no MCP client required).

## Quick start: HTTP access

These endpoints expose the in-memory MCP producer registry over plain HTTP.

> If your instance uses API auth, include `Authorization: Bearer <token>`.
> If `mcp.require_auth=true`, also include `X-MCP-Key: <key>`.

### List MCP producers

```bash
curl -s \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:5050/api/v1/mcp/producers
```

Example response:

```json
{
  "producers": [
    {
      "name": "tradfi-basis",
      "domain": "tradfi",
      "mcp_source_url": null,
      "description": "Produce basis/carry signals for the configured universe.",
      "assets": ["BTC", "ETH", "SOL"],
      "schedule": "*/30 * * * *",
      "registered_at": "2026-03-01T05:00:00+00:00",
      "latest_signal": {
        "producer": "tradfi-basis",
        "domain": "tradfi",
        "asset": "BTC",
        "direction": "long",
        "confidence": 0.72,
        "horizon": "4h",
        "reason": "Basis unwound to 1.8%, funding 0.9% — re-leveraging setup",
        "timestamp": "2026-03-01T05:00:00+00:00",
        "raw_score": 7.2,
        "metadata": {
          "event_type": "signal.tradfi_basis.v1",
          "source": "tradfi-basis"
        }
      }
    },
    {
      "name": "social-intel",
      "domain": "social",
      "mcp_source_url": null,
      "description": "",
      "assets": [],
      "schedule": "*/15 * * * *",
      "registered_at": "2026-03-01T05:00:01+00:00",
      "latest_signal": null
    }
  ],
  "count": 2
}
```

### Check MCP registry status

```bash
curl -s \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:5050/api/v1/mcp/status
```

Example response:

```json
{
  "enabled": true,
  "producer_count": 13,
  "total_signals_buffered": 847,
  "registry_ok": true
}
```

## Connecting Claude Desktop

1. Install b1e55ed with MCP extras:

   ```bash
   pip install "b1e55ed[mcp]"
   ```

2. Start b1e55ed:

   ```bash
   b1e55ed start
   ```

3. Add a Claude Desktop MCP server entry in `claude_desktop_config.json`:

   ```json
   {
     "mcpServers": {
       "b1e55ed": {
         "command": "npx",
         "args": [
           "-y",
           "mcp-remote",
           "http://127.0.0.1:7337/sse"
         ]
       }
     }
   }
   ```

4. Restart Claude Desktop.

You can now ask things like:

- "What’s the current TradFi signal?"
- "List all producers."
- "Show the last 10 onchain signals."
- "What changed in social signals in the last hour?"

## MCP tools reference

| Tool | Description | Arguments | Return shape |
|---|---|---|---|
| `list_producers()` | List producer manifests currently registered in memory. | None | `list[MCPProducerManifest]` |
| `get_latest_signal(producer_name)` | Return the newest signal for one producer. | `producer_name: str` | `MCPSignalPayload \| null` |
| `get_signal_history(producer_name, limit=10)` | Return the most recent N signals for one producer. | `producer_name: str`, `limit: int = 10` | `list[MCPSignalPayload]` |

`MCPProducerManifest` entries include:
`name`, `domain`, `mcp_source_url`, `description`, `assets`, `schedule`, `registered_at`.

## MCPSignalPayload schema

| Field | Type | Description |
|---|---|---|
| `producer` | `str` | Producer name (example: `tradfi-basis`). |
| `domain` | `str` | Signal domain (`technical`, `onchain`, `tradfi`, `social`, `events`, `curator`). |
| `asset` | `str \| null` | Asset symbol when signal is asset-specific. |
| `direction` | `str \| null` | Directional intent (`long`, `short`, `flat`) when available. |
| `confidence` | `float \| null` | Confidence in 0.0–1.0 when provided by producer. |
| `horizon` | `str \| null` | Time horizon (example: `4h`, `1d`). |
| `reason` | `str` | Human-readable rationale. |
| `timestamp` | `str` | ISO8601 UTC timestamp. |
| `raw_score` | `float \| null` | Original producer score when applicable. |
| `metadata` | `dict` | Producer-specific extra fields (event type, source, etc.). |

## Configuration

Add MCP settings to `config/user.yaml`:

```yaml
mcp:
  enabled: true
  port: 7337
  require_auth: false
  api_keys: []
```

Field behavior:

- `enabled`: starts the MCP server/registry integration.
- `port`: FastMCP server port (default `7337`).
- `require_auth`: if `true`, `/api/v1/mcp/*` endpoints require `X-MCP-Key`.
- `api_keys`: allowed key list for `X-MCP-Key` validation.

> If port `7337` is publicly exposed, set `require_auth: true` and define strong API keys.

## Adding MCP data sources (for producer authors)

Producer authors can declare upstream MCP capability via `mcp_source_url` on the producer class.

Example (`FinancialDatasetsMCPProducer`):

```python
class FinancialDatasetsMCPProducer(BaseProducer):
    name = "financial_datasets"
    domain = "tradfi"
    schedule = "0 */6 * * *"
    mcp_source_url = "https://github.com/financial-datasets/mcp-server"
```

Semantics:

- `mcp_source_url = null` → producer currently uses REST/WebSocket-style data collection.
- `mcp_source_url = <url>` → producer has an upstream MCP server available.

Today, this is a declaration + compatibility hook. When full MCP stdio protocol support lands, producers with `mcp_source_url` set will auto-switch from REST transport to direct MCP transport.

## Security

- Default `require_auth=false` is safe for local/operator deployments where port `7337` is not exposed.
- For public deployments: set `require_auth=true`, populate `api_keys`, and firewall port `7337`.
- Authenticated registry requests use the `X-MCP-Key` header.

Related docs:
- [producers.md](producers.md)
- [api-reference.md](api-reference.md)
- [configuration.md](configuration.md)
