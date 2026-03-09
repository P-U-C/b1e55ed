# Execution Pipeline Diagnosis — Orphaned Trade Intents

## Finding

**20 `execution.trade_intent.v1` events in `data/brain.db` never produced any orders, positions, or fills.**

```sql
SELECT COUNT(*) FROM events WHERE type='execution.trade_intent.v1';
-- Result: 20

SELECT COUNT(*) FROM orders;
-- Result: 0
```

## Root Cause

`BrainOrchestrator` was instantiated in `engine/cli/main.py` without the `oms=` keyword argument:

```python
# BEFORE (broken) — engine/cli/main.py ~line 857
orchestrator = BrainOrchestrator(
    config=config,
    db=db,
    identity=identity,
    # oms= missing
)
```

Inside the orchestrator's auto-paper-trade path:

```python
# engine/brain/orchestrator.py
if self._oms is None:
    logger.debug("auto-paper-trade skipped: no OMS injected")
    return  # ← all 20 intents hit this
```

The `DecisionEngine.decide_and_emit()` correctly emitted `trade_intent` events to the event log, but the OMS consumer was never attached, so **no order was ever submitted to PaperBroker**.

## Second Bug

Even if OMS had been wired in, every position would have been priced at `$1.00`:

```python
# BEFORE — engine/brain/orchestrator.py
oms.submit(intent, mid_price=1.0, ...)  # ← wrong
```

## Fix Applied (PR #354)

```python
# AFTER — engine/cli/main.py
from engine.execution.oms import OMS, default_sizer_from_config
from engine.execution.preflight import Preflight

oms = OMS(
    config=config,
    db=db,
    preflight=Preflight(policy=policy_engine, kill_switch=kill_switch),
    sizer=default_sizer_from_config(config),
)
orchestrator = BrainOrchestrator(
    config=config,
    db=db,
    identity=identity,
    oms=oms,          # ← wired
)
```

```python
# AFTER — engine/brain/orchestrator.py
def _resolve_mid_price(self, symbol: str) -> float | None:
    """Query DB for latest PRICE_V1 event, fallback to Binance public API."""
    ...  # returns real price or None (skips trade, never uses 1.0)
```

## Impact

All 20 orphaned intents represent missed paper trades during the period 2026-01-xx → 2026-03-06. These cannot be retroactively filled. Going forward, every brain cycle will submit real paper trades via OMS → PaperBroker → positions table.

## Verification

```bash
./scripts/run_execution_e2e.sh
# Stage 6 (orphan_diagnosis) confirms:
# oms_now_wired=True  mid_price_fixed=True
# CONFIRMED: 20 intents, 0 orders. Root cause: BrainOrchestrator created without oms= kwarg
```
