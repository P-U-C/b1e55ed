# Oracle

The oracle is a read-only, publicly accessible projection layer over the event store.

It answers one question: **does this signal producer have verifiable history?**

## Endpoint

```
GET /api/v1/oracle/producers/{producer_id}/provenance
```

No authentication required. Designed to be queried by AI agents before acting on a signal.

Anti-Goodhart header on every response:

```
X-Attribution-Notice: Fields informational only. May change without notice. Optimizing against specific metrics triggers drift detection.
```

## Response

**Producer with history:**

```json
{
  "producer_id": "alpha_signals_v2",
  "has_provenance": true,
  "chain_verified": true,
  "chain_integrity_spot_checked": true,
  "total_signals": 142,
  "p_and_l_attributed": true,
  "operator_coverage": 3,
  "first_seen": "2026-01-15",
  "last_seen": "2026-02-20",
  "attribution_windows": {
    "7d": {"signals": 18, "hit_rate": 0.72, "max_drawdown_pct": -3.1},
    "30d": {"signals": 62, "hit_rate": 0.67, "max_drawdown_pct": -8.4},
    "90d": {"signals": 142, "hit_rate": 0.61, "max_drawdown_pct": -14.2}
  },
  "note": "Historical attribution data. Not a predictive rating. Agent decides weighting."
}
```

**Unknown producer:**

```json
{
  "producer_id": "unknown_source",
  "has_provenance": false,
  "note": "No provenance data available. Proceeding without attribution context."
}
```

## Response fields

| Field | Type | Description |
|-------|------|-------------|
| `has_provenance` | bool | Whether any events exist for this producer |
| `chain_verified` | bool | Backwards-compat alias for `chain_integrity_spot_checked` |
| `chain_integrity_spot_checked` | bool | Last 100 events in the global hash chain passed cryptographic verification. This is a lightweight spot-check, not a full chain audit. Use `b1e55ed integrity` for full verification. |
| `total_signals` | int | Total signals in the event store |
| `p_and_l_attributed` | bool | At least one karma settlement references this producer |
| `operator_coverage` | int | Distinct nodes that have observed this producer |
| `attribution_windows` | object | Per-window hit rates and drawdowns |

## Identity semantics (`source` vs `node_id`)

- **Canonical producer identity is `node_id`** when a signal is linked to a registered contributor.
- Oracle lookups accept either the canonical `node_id` **or** a historical `events.source` alias.
- When an alias resolves unambiguously to a contributor, the response `producer_id` returns the canonical `node_id`.

This keeps provenance queries coherent across legacy source labels and contributor-linked submissions.

## MCP tool

The `b1e55ed_provenance_check` MCP tool wraps this endpoint for agent use.

Via `POST /api/v1/mcp`:

```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "id": 1,
  "params": {
    "name": "b1e55ed_provenance_check",
    "arguments": {
      "producer_id": "alpha_signals_v2",
      "signal_type": "long_btc"
    }
  }
}
```

See: [agent-interfaces.md](agent-interfaces.md) for full MCP server documentation.

## Karma scoring

The oracle draws on karma scores described in `docs/KARMA-SPEC.md`.

Scores are NOT returned by the provenance endpoint — the endpoint returns facts. Karma calibration, update rules, and failure modes are specified in KARMA-SPEC.md.

## Query logging

Every oracle query is logged to `data/oracle_queries.jsonl` in anonymized form:

```json
{"ts": 1234567890, "producer_id_hash": "a1b2c3d4", "signal_type": "long_btc", "has_provenance": true}
```

Raw producer IDs are never logged. This data is demand intelligence — it never feeds back into karma scores.

## Reproducibility

`docs/SEED_MANIFEST.md` documents the initial seed dataset and how to verify scores are reproducible.
