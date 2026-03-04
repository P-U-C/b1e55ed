# MCP Sprint Plan — b1e55ed MCP-Native Producers

> Producers as bidirectional MCP nodes: consume data via MCP (inbound), expose signals via MCP (outbound).
> Branch strategy mirrors flywheel: `feat/mcp` off `develop`, sprint branches off `feat/mcp`.

---

## Goal

Make every b1e55ed producer a first-class MCP citizen:

- **Inbound**: If a data source exposes an MCP server, producers consume it via MCP client (fallback to REST if not).
- **Outbound**: Every producer's signals are exposed via a single MCP server. External agents (Claude, agent builders, oracles) subscribe to live signals without touching the REST API.

This turns b1e55ed from an internal trading system into **externally-consumable signal infrastructure**.

---

## Branch Strategy

```
develop  (stable)
└── feat/mcp  (integration branch, draft PR → develop)
    ├── mcp/s0-spec-foundation
    ├── mcp/s1-client-inbound
    ├── mcp/s2-server-outbound
    ├── mcp/s3-wire-producers
    ├── mcp/s4-auth-external-access
    └── mcp/s5-docs
```

**Rules (same as flywheel):**
- Sprint branches PR into `feat/mcp` (not develop)
- `feat/mcp` stays draft PR to `develop` — **never auto-merge**
- Codex implements; Opus reviews/specs
- Human merges only — not automated

---

## Conflict Isolation (Critical)

Both `feat/flywheel` and `feat/mcp` branch off `develop` and run in parallel.

### Flywheel files (⚠️ avoid or coordinate):
```
engine/brain/orchestrator.py     ← HIGH RISK — flywheel heavily modified
engine/core/types.py             ← flywheel extended ConvictionScore/TradeIntent
engine/core/events.py            ← flywheel added SIGNAL_ACCEPTED_V1 etc.
engine/core/database.py          ← flywheel added 4 new tables
engine/producers/tradfi.py       ← flywheel rewrote TradFiBasisProducer
engine/producers/benchmarks.py   ← flywheel added (new file, but flywheel owns it)
api/routes/__init__.py           ← flywheel added cockpit + benchmarks routers
engine/execution/oms.py          ← flywheel wired attribution
```

### MCP sprint owns (✅ safe, no flywheel overlap):
```
engine/mcp/                      ← NEW module, zero conflict
engine/producers/base.py         ← NOT touched by flywheel
engine/producers/registry.py     ← NOT touched by flywheel
api/routes/mcp.py                ← NEW route file
pyproject.toml                   ← add mcp dep only (low risk, 1-line change)
docs/mcp.md                      ← NEW doc file
```

### Architecture decision that makes this possible:
**The brain orchestrator is NOT touched in the MCP sprint.**

MCP is a parallel emission path, not a replacement for direct signal flow. Producers emit to the DB (existing) AND to the MCP server (new). The brain keeps reading from DB/direct call. Only after flywheel merges into develop should we consider MCP as an aggregation layer for the brain.

```
Producer.publish()
├── → DB (existing, unchanged)
├── → Brain direct (existing, unchanged)
└── → MCP Server (new, additive)
         └── External agents subscribe here
```

---

## Architecture

### Single MCP Server (not per-producer)

One MCP server process, many resources:

```
b1e55ed MCP Server (port configurable, default 7337)
├── Resource: signal://tradfi/latest
├── Resource: signal://onchain/latest
├── Resource: signal://sentiment/latest
├── Resource: signal://technical/latest
├── Resource: signal://benchmark/momentum/latest
├── ...all producers as resources
├── Tool: get_latest_signal(producer_name)
├── Tool: get_signal_history(producer_name, limit)
├── Tool: list_producers()
└── Tool: get_brain_conviction()   ← after flywheel merges
```

### Bidirectional Producer Base

```python
class BaseProducer(ABC):
    # existing fields
    name: str
    domain: str
    schedule: str
    
    # NEW: MCP inbound (optional — None = use REST)
    mcp_source_url: str | None = None
    
    async def collect(self) -> list[dict]:
        if self.mcp_source_url:
            return await self._collect_via_mcp()
        return await self._collect_via_api()   # existing behavior
    
    def publish(self, events: list[Event]) -> int:
        count = self._publish_to_db(events)    # existing
        self._publish_to_mcp(events)           # NEW (non-blocking, fire-and-forget)
        return count
    
    async def _collect_via_mcp(self) -> list[dict]: ...
    def _publish_to_mcp(self, events: list[Event]) -> None: ...
```

---

## Sprint Breakdown

### S0 — Spec & Foundation
**Branch**: `mcp/s0-spec-foundation` → `feat/mcp`
**Files**: `engine/mcp/__init__.py`, `engine/mcp/types.py`, `docs/MCP_SPEC.md`, `pyproject.toml`

**Deliverables:**
- `engine/mcp/types.py` — `MCPSignalResource`, `MCPProducerManifest`, `MCPSignalPayload`
- `engine/mcp/__init__.py` — package skeleton
- `docs/MCP_SPEC.md` — this document + schema definitions
- Add `mcp[cli]` to `pyproject.toml` dependencies
- 0 test additions (spec sprint)

**Schema (locked):**
```python
@dataclass
class MCPSignalPayload:
    producer: str
    domain: str
    asset: str | None
    direction: str | None        # "long" | "short" | "flat" | None
    confidence: float | None     # 0.0–1.0
    horizon: str | None          # e.g. "4h", "1d"
    reason: str
    timestamp: str               # ISO8601
    raw_score: float | None      # original 0–10 score if applicable
    metadata: dict               # producer-specific extras
```

**Conflict risk**: Zero (new files + 1-line pyproject.toml change)

---

### S1 — MCP Client (Inbound)
**Branch**: `mcp/s1-client-inbound` → `feat/mcp`
**Files**: `engine/mcp/client.py`, `engine/producers/base.py`, `engine/producers/financial_datasets.py`, `tests/unit/test_mcp_client.py`

**Deliverables:**
- `engine/mcp/client.py` — generic async MCP client wrapper
  - `MCPClient.connect(url)` — connects to any MCP server
  - `MCPClient.call_tool(name, args)` → normalized result
  - `MCPClient.get_resource(uri)` → normalized result
  - Connection pooling + timeout handling
- `BaseProducer.mcp_source_url: str | None = None` — new optional field
- `BaseProducer._collect_via_mcp()` — uses `MCPClient`, normalizes to `list[dict]`
- `BaseProducer.collect()` — now async-aware, dispatches to MCP or existing API path
- `FinancialDatasetsMCPProducer` — first real MCP-consuming producer
  - Source: `financial-datasets/mcp-server` (requires `FINANCIAL_DATASETS_API_KEY`)
  - Emits earnings signals, fundamental alerts, price-vs-consensus divergences
  - Falls back gracefully if MCP server unreachable
- Unit tests: mock MCP server, verify client dispatch, test fallback path

**Conflict risk**: Low — `base.py` safe; new producer file; new `engine/mcp/` files

---

### S2 — MCP Server (Outbound)
**Branch**: `mcp/s2-server-outbound` → `feat/mcp`
**Files**: `engine/mcp/server.py`, `engine/mcp/registry.py`, `tests/unit/test_mcp_server.py`

**Deliverables:**
- `engine/mcp/server.py` — single MCP server exposing all producers
  - Runs as async background task alongside FastAPI
  - Each producer registers its signal resource on startup
  - `get_latest_signal(producer_name)` tool — returns last `MCPSignalPayload`
  - `get_signal_history(producer_name, limit=10)` tool
  - `list_producers()` tool — returns manifest of all registered producers
  - Signal buffer: last 100 signals per producer in-memory (no DB dependency)
- `engine/mcp/registry.py` — `MCPProducerRegistry`
  - Producers self-register on init
  - Registry feeds server's resource list
  - Thread-safe signal buffer per producer
- `BaseProducer._publish_to_mcp(events)` — fire-and-forget push to registry
  - Non-blocking (try/except, never crashes producer run loop)
  - Converts `Event` → `MCPSignalPayload`
- Unit tests: server startup/shutdown, tool invocations, buffer rotation

**Conflict risk**: Zero — all new files in `engine/mcp/`; `base.py` addition is additive

---

### S3 — Wire All Existing Producers
**Branch**: `mcp/s3-wire-producers` → `feat/mcp`
**Files**: All producer files in `engine/producers/`

**Deliverables:**
- Verify every existing producer inherits updated `BaseProducer` and emits to MCP
- Set `mcp_source_url = None` default explicitly (documents intent)
- MCP server integration test: start server → run each producer → verify signal appears
- Update `engine/producers/registry.py` to register with `MCPProducerRegistry` on load

**Conflict risk** (the careful sprint):
- `engine/producers/tradfi.py` — touched by flywheel (S3). **Approach**: minimal change (inherit from updated base, add `mcp_source_url = None`). If merge conflict arises, take flywheel's version + add the one-liner.
- `engine/producers/benchmarks.py` — same approach
- All other producers: safe (flywheel didn't touch them)

**Rule**: MCP sprint only ADDS to existing producers, never modifies logic. One-liners only on flywheel-owned files.

---

### S4 — External Access + Auth
**Branch**: `mcp/s4-auth-external` → `feat/mcp`
**Files**: `engine/mcp/auth.py`, `api/routes/mcp.py`, `engine/core/config.py` (additive)

**Deliverables:**
- `engine/mcp/auth.py` — API key validation for MCP connections
  - Validates against `config.mcp.api_keys` list
  - Rate limiting per key
- `api/routes/mcp.py` — NEW route file (not touching `__init__.py` yet — avoid conflict)
  - `GET /api/v1/mcp/producers` — list all MCP-exposed producers + their resource URIs
  - `GET /api/v1/mcp/status` — server health, connected clients, signal rates
- MCP server config block in `engine/core/config.py`:
  ```toml
  [mcp]
  enabled = true
  port = 7337
  require_auth = false   # set true in production
  api_keys = []
  ```
- Wire `api/routes/mcp.py` into `api/routes/__init__.py`
  - **Conflict risk**: `__init__.py` touched by flywheel. **Approach**: add a single `include_router(mcp.router)` line. If conflict, take flywheel's version + add the line at the bottom.

**Conflict risk**: Low-medium on `__init__.py` only; everything else is new

---

### S5 — Docs + Operator Guide
**Branch**: `mcp/s5-docs` → `feat/mcp`
**Files**: `docs/mcp.md`, `docs/producers.md`, `docs/dependencies-docs.md`

**Deliverables:**
- `docs/mcp.md` — operator guide: how to connect Claude/external agents to live producer signals
  - Connecting Claude Desktop to b1e55ed MCP server
  - Available tools and resources
  - Authentication setup
  - Example: "What's the current TradFi signal?" via Claude
- `docs/producers.md` — update with MCP capability table (which producers have MCP source URLs)
- `docs/dependencies-docs.md` — register `mcp.md` and `financial_datasets.py`
- `docs/api-reference.md` — add `/api/v1/mcp/*` endpoints

**Conflict risk**: `docs/dependencies-docs.md` touched by flywheel docs sweep. Take flywheel's version + add entries.

---

## Merge Strategy (When Flywheel + MCP Both Ready)

When both feature branches are ready for `develop`:

1. Merge `feat/flywheel` → `develop` first (it's further along)
2. Rebase `feat/mcp` onto new `develop`
3. Resolve conflicts (mostly `tradfi.py`, `benchmarks.py`, `__init__.py`) — all additive, no logic conflicts expected
4. Run full test suite on rebased `feat/mcp`
5. Open final PR + merge

**No inter-branch dependencies** — MCP sprint never imports from flywheel modules and vice versa.

---

## Success Criteria

- [ ] Every producer emits to MCP server on publish (verified by integration test)
- [ ] `list_producers()` tool returns all registered producers
- [ ] `get_latest_signal("tradfi")` returns last TradFi signal
- [ ] `FinancialDatasetsMCPProducer` ingests earnings data via MCP client
- [ ] MCP server starts with FastAPI app, stops cleanly on shutdown
- [ ] External Claude session can call `list_producers()` and `get_latest_signal()` via MCP
- [ ] No flywheel tests broken by MCP changes
- [ ] MCP server failure does NOT crash producer run loop (fully isolated)
- [ ] All existing 666+ tests still pass

---

## What This Unlocks (Post-Merge)

- **Oracle consumers** subscribe to live signals via MCP — no REST polling
- **Claude sessions** can query "what does the TradFi producer see right now?" directly
- **Any MCP-compatible data source** (financial-datasets or future) plugs in with zero brain changes
- **External agent builders** get standardized signal access without API key setup per-endpoint
- **Brain MCP aggregator** (future sprint, after flywheel stable) — brain subscribes to producers via MCP, closes the loop entirely

---

*Created: 2026-03-01*
*Status: SPEC — not yet branched*
*Parallel branch: `feat/flywheel` (do not merge into feat/mcp)*
