# Authority Model

> Single-writer event store with explicit concurrency rules.

## The One-Writer Rule

b1e55ed uses an append-only event store backed by SQLite. The hash chain — where each event's hash includes its predecessor — requires **exactly one writer** at any time.

**Violation of this rule forks the chain.** Two processes appending concurrently will produce events with the same `prev_hash`, creating an irrecoverable fork.

## How It's Enforced

### SQLite WAL Mode

The database runs in WAL (Write-Ahead Logging) mode:

```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
```

WAL allows concurrent reads but serializes writes. However, SQLite's write lock is per-transaction — it does not prevent two processes from interleaving transactions.

### Application-Level Lock

`Database` uses a `threading.RLock` around all write operations. This prevents concurrent writes **within a single process**. It does not protect across processes.

### Transaction-Local Hash Read

The `prev_hash` for each new event is read from the database **inside the transaction**, not from a cached value. This means:

- If another writer somehow appended between transactions, the next write will see the updated hash.
- The cached `_last_hash` is synchronized after each read.

```python
# Inside _append_event_inner:
db_last = self.conn.execute(
    "SELECT hash FROM events ORDER BY created_at DESC, rowid DESC LIMIT 1"
).fetchone()
prev = str(db_last[0]) if db_last else self.GENESIS_PREV_HASH
```

### Concurrent Writer Detection

`b1e55ed integrity` checks for concurrent writers by attempting an `IMMEDIATE` transaction. If another process holds a write lock, it fails fast.

## Operator Rules

1. **One brain process.** Do not run multiple `b1e55ed brain` instances against the same database.
2. **One API server.** The API server writes events (signal submission). Do not run multiple API instances without a write proxy.
3. **Cron jobs are safe** if they use the CLI (which opens/closes the DB per invocation) — but they must not overlap with brain cycles.
4. **Read replicas are fine.** SQLite WAL mode supports concurrent readers. Dashboard, queries, and monitoring can read freely.

## Fork Detection

If the one-writer rule is violated, `b1e55ed integrity` will detect it:

```bash
b1e55ed integrity --json
```

A hash chain failure means events were appended out of order. Recovery requires:

1. Identify the fork point (last valid hash).
2. Discard events after the fork.
3. Re-append from the correct chain.

This is a manual process. Prevention is the only practical strategy.

## Producer Trust Boundaries

Producers submit signals via authenticated API endpoints. They are **trusted to provide data** but **not trusted to be correct**.

The trust model:

| Layer | Trust Level | Enforcement |
|-------|-------------|-------------|
| Authentication | High | API token + `hmac.compare_digest` |
| Signal format | Medium | Schema validation on ingestion |
| Signal quality | Low | Scoring, rate limiting, anti-spam |
| Signal correctness | None | Brain evaluates; karma settles |

Producers cannot:
- Write events directly (only via API signal submission).
- Modify existing events (append-only store).
- Affect other producers' signals (isolated contributor IDs).
- Bypass rate limits or role permissions.

Producers can potentially:
- Submit misleading signals (mitigated by scoring + karma).
- Flood the system (mitigated by rate limiting).
- Coordinate with other producers (mitigated by correlation detection, planned).

## Future: Multi-Node

If b1e55ed ever supports multiple writers (e.g., distributed deployment):

- Replace SQLite with a consensus-based store.
- Or use a single writer with replicated reads (current architecture scales to this).
- Hash chain becomes a Merkle tree with merge semantics.

For v1, single-writer SQLite is the correct choice. It's simple, fast, and the authority model is unambiguous.
