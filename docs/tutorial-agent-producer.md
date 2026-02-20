# Building an Agent Producer for b1e55ed

## 1. What is a Producer

A producer is a signal source that feeds the brain. Producers emit events that the engine can weight, audit, and learn from.

A producer can be:
- a service you run (HTTP endpoint)
- an agent process that periodically publishes signals
- an internal module bundled with b1e55ed

The brain does not require a specific agent framework. It requires a stable JSON contract.

## 2. The Producer Contract

A minimal producer response is a JSON object with a producer identity, a domain, and a list of signals.

```json
{
  "producer": "my-scanner",
  "domain": "technical",
  "signals": [
    {
      "asset": "BTC",
      "direction": "bullish",
      "score": 7.2,
      "confidence": 0.8,
      "reasoning": "Golden cross on daily"
    }
  ]
}
```

Guidelines:
- `producer` is a stable name. Treat it as an identifier.
- `domain` should match one of the engine domains (technical, onchain, tradfi, social, events, curator).
- `score` is a 0–10 strength signal.
- `confidence` is a 0–1 reliability estimate.
- `reasoning` should be concise. The corpus is long-lived.

## 3. Build a Minimal Producer

A minimal FastAPI producer can be a single route that returns the contract.

```python
from __future__ import annotations

from fastapi import FastAPI

app = FastAPI()


@app.get("/signals")
def signals() -> dict[str, object]:
    return {
        "producer": "my-scanner",
        "domain": "technical",
        "signals": [
            {
                "asset": "BTC",
                "direction": "bullish",
                "score": 7.2,
                "confidence": 0.8,
                "reasoning": "Golden cross on daily",
            }
        ],
    }
```

Run it:

```bash
uvicorn producer:app --host 0.0.0.0 --port 9000
```

## 4. Register with b1e55ed

Register the producer endpoint:

```bash
b1e55ed producers register --name my-scanner --domain technical --endpoint http://localhost:9000/signals
```

This stores the producer metadata so the operator layer can manage it.

## 5. Verify Ingestion

Verify ingestion by inspecting the event store.

For local development, you can query the SQLite database directly:

```bash
sqlite3 data/brain.db \
  "SELECT type, ts, source, json_extract(payload, '$.symbol') FROM events WHERE type LIKE 'signal.%' ORDER BY ts DESC LIMIT 20;"
```

If you are operating remotely, query the API routes that expose recent events (operator layer) or consume webhook deliveries.

## 6. Monitor Health

Health exposes configuration and DB reachability, plus degraded producer status.

```bash
b1e55ed health --json
```

## 7. OpenClaw Integration

OpenClaw operators typically schedule producers and brain cycles as cron templates.

Recommended pattern:
- producer runs publish signals on a cadence
- a brain cycle runs every 5 minutes
- health checks run hourly

Use the included `crons.json` templates as a starting point. For example, wire a system event that executes:

```bash
cd /path/to/b1e55ed && uv run b1e55ed brain --json
```

Keep producer processes isolated. If a producer fails, the brain should still run and the corpus should remain consistent.
