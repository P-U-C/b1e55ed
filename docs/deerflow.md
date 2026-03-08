# DeerFlow Integration

Connect [DeerFlow](https://github.com/bytedance/deer-flow) research agents to
b1e55ed's MCP tool surface.  DeerFlow orchestrates multi-step research
workflows; b1e55ed provides regime awareness, signal provenance, and position
context.

## Prerequisites

- Python 3.11+
- b1e55ed running (`python -m b1e55ed.server` or deployed instance)
- DeerFlow installed ([setup guide](https://github.com/bytedance/deer-flow#quickstart))

## Quick Start — Direct Mode

Direct mode runs b1e55ed's MCP server as a DeerFlow subprocess.

```bash
# 1. Install b1e55ed
pip install -e .

# 2. Copy the DeerFlow extension config
cp integrations/deerflow/extensions_config.json \
   $DEERFLOW_HOME/extensions/b1e55ed.json

# 3. Start DeerFlow — it spawns b1e55ed MCP automatically
deerflow start
```

DeerFlow will launch `python -m b1e55ed.mcp` and discover all available tools
via the MCP `tools/list` handshake.

## Gateway Mode

For teams or remote deployments, run the b1e55ed MCP Gateway and point DeerFlow
at it over HTTP.

```bash
# 1. Start the gateway
cd gateway
pip install -r requirements.txt
# Edit config.yaml — set b1e55ed_url, generate API keys
uvicorn gateway.main:app --host 0.0.0.0 --port 7338

# 2. Configure DeerFlow
export B1E55ED_API_KEY="analyst-key-change-me"
# Use the "gateway" mode from extensions_config.json
```

The gateway adds role-based access control, audit logging, and a signal approval
workflow.  See `gateway/README.md` for details.

## Available MCP Tools

| Tool | Description | Min Role |
|------|-------------|----------|
| `get_brain_status` | Current brain state, regime, and confidence | analyst |
| `get_recent_signals` | Latest signals with optional filters | analyst |
| `get_regime_status` | Active regime with transition history | analyst |
| `get_top_signals` | Highest-conviction signals by score | analyst |
| `get_regime_history` | Historical regime transitions | analyst |
| `get_signals_bulk_export` | Bulk signal export (CSV/JSON) | analyst |
| `get_open_positions` | Current open positions with PnL | pm |
| `get_signal_attribution` | Karma attribution for a signal | pm |
| `b1e55ed_provenance_check` | Verify signal provenance chain | risk |
| `submit_research_signal` | Submit a new research signal (queued if non-admin) | admin* |
| `emit_producer_signal` | Emit a raw producer signal | admin |

*Non-admin roles can call `submit_research_signal` through the gateway, but it
queues for admin approval instead of forwarding directly.

## Skill Pack

DeerFlow's skill system can import b1e55ed tools as a skill pack.  The
extension config at `integrations/deerflow/extensions_config.json` exposes both
direct and gateway modes.

A typical DeerFlow research workflow:

1. **Scout** — `get_regime_status` to understand market context
2. **Gather** — `get_recent_signals` + `get_top_signals` for current alpha
3. **Verify** — `b1e55ed_provenance_check` on interesting signals
4. **Report** — DeerFlow synthesises findings with regime context

## Signal Provenance

Every signal in b1e55ed carries a provenance chain.  DeerFlow agents should call
`b1e55ed_provenance_check` before acting on any signal to verify:

- Producer identity and registration status
- Karma score of the originating producer
- Chain of custody from raw data to synthesised signal

This prevents DeerFlow from acting on unverified or low-quality signals.

## MCP Protocol

b1e55ed speaks JSON-RPC 2.0 over the MCP transport:

```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "get_regime_status",
    "arguments": {}
  },
  "id": 1
}
```

POST to `/mcp/call` (direct or gateway).

## Troubleshooting

### DeerFlow can't discover tools

- **Direct mode:** Ensure `python -m b1e55ed.mcp` runs without errors.
  Check that the database exists at the configured `B1E55ED_DB` path.
- **Gateway mode:** Verify the gateway is running (`curl http://localhost:7338/health`).

### 401 Unauthorized

- Check `X-API-Key` header matches a key in `gateway/config.yaml`.

### Tool call returns "Role X cannot call Y"

- The user's role doesn't include that tool.  See the role table above or
  ask an admin to upgrade the key's role in `config.yaml`.

### Signal queued instead of executed

- Non-admin `submit_research_signal` calls are queued by design.
  An admin must approve via `POST /approve/{signal_id}`.

### Gateway health shows b1e55ed unreachable

- Check `b1e55ed_url` in `config.yaml` points to the running instance.
- If using a token, verify `b1e55ed_token` is correct.

### Audit log location

- All requests are logged to `gateway/data/audit.jsonl`.
- Each entry includes timestamp, user, tool, redacted params, and status.
