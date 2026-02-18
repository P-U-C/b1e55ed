"""engine.core.database

A grimoire is not a textbook — it is a book of hard-won procedures.

This database is the journal: append-only events with a hash chain.
If you cannot remember the past, you will repeat it.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from engine.core.events import EventType, canonical_json
from engine.core.exceptions import DedupeConflictError, EventStoreError
from engine.core.models import Event, compute_event_hash

SCHEMA = """
-- ============================================================
-- Schema Version Tracking
-- ============================================================
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- Core Events (hash chain, append-only)
-- ============================================================
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    ts TEXT NOT NULL,
    observed_at TEXT,
    source TEXT,
    trace_id TEXT,
    schema_version TEXT DEFAULT 'v1',
    dedupe_key TEXT,
    payload TEXT NOT NULL,
    prev_hash TEXT,
    hash TEXT NOT NULL UNIQUE,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_dedupe ON events(dedupe_key);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(source);

-- ============================================================
-- Event Deduplication
-- ============================================================
CREATE TABLE IF NOT EXISTS event_dedup (
    dedupe_key TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id),
    payload_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_event_dedup_event_id ON event_dedup(event_id);

-- ============================================================
-- Feature Snapshots (reproducibility)
-- ============================================================
CREATE TABLE IF NOT EXISTS feature_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    ts TEXT NOT NULL,
    features TEXT NOT NULL,
    source_event_ids TEXT,
    regime TEXT,
    version TEXT DEFAULT 'v1',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_snapshots_cycle ON feature_snapshots(cycle_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_symbol ON feature_snapshots(symbol);
CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON feature_snapshots(ts);

-- ============================================================
-- Conviction Scores
-- ============================================================
CREATE TABLE IF NOT EXISTS conviction_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id TEXT,
    node_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('long', 'short', 'neutral')),
    magnitude REAL NOT NULL CHECK(magnitude >= 0 AND magnitude <= 10),
    timeframe TEXT NOT NULL,
    ts TEXT NOT NULL,
    commitment_hash TEXT NOT NULL,
    signature TEXT,
    pcs_score REAL,
    cts_score REAL,
    regime TEXT,
    domains_used TEXT,
    confidence REAL,
    metadata TEXT,
    outcome REAL,
    outcome_ts TEXT
);

CREATE INDEX IF NOT EXISTS idx_scores_symbol ON conviction_scores(symbol);
CREATE INDEX IF NOT EXISTS idx_scores_ts ON conviction_scores(ts);
CREATE INDEX IF NOT EXISTS idx_scores_node ON conviction_scores(node_id);
CREATE INDEX IF NOT EXISTS idx_scores_cycle ON conviction_scores(cycle_id);

-- ============================================================
-- Positions (projection from events)
-- ============================================================
CREATE TABLE IF NOT EXISTS positions (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    asset TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('long', 'short')),
    entry_price REAL NOT NULL,
    size_notional REAL NOT NULL,
    leverage REAL DEFAULT 1.0,
    margin_type TEXT DEFAULT 'isolated' CHECK(margin_type IN ('isolated', 'cross')),
    stop_loss REAL,
    take_profit REAL,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    status TEXT DEFAULT 'open' CHECK(status IN (
        'open', 'monitoring', 'degrading', 'closing', 'closed', 'liquidated'
    )),
    realized_pnl REAL,
    conviction_id INTEGER,
    regime_at_entry TEXT,
    pcs_at_entry REAL,
    cts_at_entry REAL,
    max_drawdown_during REAL,
    max_favorable_during REAL
);

CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_positions_asset ON positions(asset);

-- ============================================================
-- Orders
-- ============================================================
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    position_id TEXT REFERENCES positions(id),
    venue TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('market', 'limit', 'stop', 'stop_limit')),
    side TEXT NOT NULL CHECK(side IN ('buy', 'sell')),
    symbol TEXT NOT NULL,
    size REAL NOT NULL,
    price REAL,
    stop_price REAL,
    fill_price REAL,
    fill_size REAL,
    status TEXT DEFAULT 'pending' CHECK(status IN (
        'pending', 'submitted', 'partial', 'filled', 'canceled', 'rejected', 'failed'
    )),
    idempotency_key TEXT UNIQUE,
    created_at TEXT DEFAULT (datetime('now')),
    filled_at TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_position ON orders(position_id);

-- ============================================================
-- Balances
-- ============================================================
CREATE TABLE IF NOT EXISTS balances (
    venue TEXT NOT NULL,
    asset TEXT NOT NULL,
    amount REAL NOT NULL,
    last_reconciled TEXT NOT NULL,
    PRIMARY KEY (venue, asset)
);

-- ============================================================
-- Karma Intents
-- ============================================================
CREATE TABLE IF NOT EXISTS karma_intents (
    id TEXT PRIMARY KEY,
    trade_id TEXT NOT NULL,
    realized_pnl_usd REAL NOT NULL,
    karma_percentage REAL NOT NULL,
    karma_amount_usd REAL NOT NULL,
    node_id TEXT NOT NULL,
    signature TEXT,
    settled INTEGER DEFAULT 0,
    batch_id TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_karma_intents_settled ON karma_intents(settled);

-- ============================================================
-- Karma Settlements
-- ============================================================
CREATE TABLE IF NOT EXISTS karma_settlements (
    id TEXT PRIMARY KEY,
    intent_ids TEXT NOT NULL,
    total_usd REAL NOT NULL,
    destination_wallet TEXT NOT NULL,
    tx_hash TEXT,
    status TEXT DEFAULT 'pending' CHECK(status IN (
        'pending', 'submitted', 'confirmed', 'failed'
    )),
    signature TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- Conviction Log (learning data)
-- ============================================================
CREATE TABLE IF NOT EXISTS conviction_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    domain TEXT NOT NULL,
    domain_score REAL NOT NULL,
    domain_weight REAL NOT NULL,
    weighted_contribution REAL NOT NULL,
    ts TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conviction_log_cycle ON conviction_log(cycle_id);
CREATE INDEX IF NOT EXISTS idx_conviction_log_symbol ON conviction_log(symbol);

-- ============================================================
-- Producer Health
-- ============================================================
CREATE TABLE IF NOT EXISTS producer_health (
    name TEXT PRIMARY KEY,
    domain TEXT,
    schedule TEXT,
    last_run_at TEXT,
    last_success_at TEXT,
    last_error TEXT,
    consecutive_failures INTEGER DEFAULT 0,
    events_produced INTEGER DEFAULT 0,
    avg_duration_ms REAL,
    expected_interval_ms INTEGER,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- Learning Weights (adjustment history)
-- ============================================================
CREATE TABLE IF NOT EXISTS learning_weights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_type TEXT NOT NULL CHECK(cycle_type IN ('daily', 'weekly', 'monthly')),
    domain TEXT NOT NULL,
    old_weight REAL NOT NULL,
    new_weight REAL NOT NULL,
    delta REAL NOT NULL,
    reason TEXT,
    approved INTEGER DEFAULT 0,
    approved_by TEXT,
    ts TEXT NOT NULL,
    reverted INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_learning_weights_ts ON learning_weights(ts);

-- ============================================================
-- Producer Scores (learning data)
-- ============================================================
CREATE TABLE IF NOT EXISTS producer_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    producer TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    signals_emitted INTEGER NOT NULL,
    signals_correct INTEGER NOT NULL,
    accuracy REAL NOT NULL,
    staleness_rate REAL NOT NULL,
    error_rate REAL NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    ts TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_producer_scores_producer ON producer_scores(producer);

-- ============================================================
-- Risk Triggers (audit)
-- ============================================================
CREATE TABLE IF NOT EXISTS risk_triggers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_type TEXT NOT NULL,
    level INTEGER,
    details TEXT,
    ts TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- Audit Log
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT DEFAULT (datetime('now')),
    action TEXT NOT NULL,
    actor TEXT,
    component TEXT,
    details TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);

-- ============================================================
-- Pattern Matches (corpus integration)
-- ============================================================
CREATE TABLE IF NOT EXISTS pattern_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_id TEXT NOT NULL,
    matched_at TEXT NOT NULL,
    market_state TEXT,
    boost_applied TEXT,
    outcome REAL,
    outcome_ts TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


def _dt_to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def _iso_to_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    # Accept Z suffix
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@dataclass
class Database:
    """Event-sourced SQLite database with hash chain."""

    db_path: Path

    def __post_init__(self) -> None:
        self.db_path = Path(self.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._init_schema()
        self._last_hash = self._get_last_hash()

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
        with self.conn:
            self.conn.executescript(SCHEMA)
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA foreign_keys=ON")

    def _get_last_hash(self) -> str | None:
        row = self.conn.execute(
            "SELECT hash FROM events ORDER BY created_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
        return None if row is None else str(row[0])

    @staticmethod
    def _payload_hash(payload: dict[str, Any]) -> str:
        import hashlib

        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

    def append_event(
        self,
        *,
        event_type: EventType,
        payload: dict[str, Any],
        event_id: str | None = None,
        observed_at: datetime | None = None,
        source: str | None = None,
        trace_id: str | None = None,
        schema_version: str = "v1",
        dedupe_key: str | None = None,
        ts: datetime | None = None,
    ) -> Event:
        """Append a single event.

        Dedup semantics:
        - If dedupe_key is new: insert.
        - If dedupe_key exists with same payload_hash: idempotent (return existing event).
        - If dedupe_key exists with different payload_hash: conflict.
        """

        with self._lock:
            now = ts or datetime.now(tz=UTC)
            if now.tzinfo is None:
                now = now.replace(tzinfo=UTC)

            payload_canon = json.loads(canonical_json(payload))
            p_hash = self._payload_hash(payload_canon)

            if dedupe_key is not None:
                row = self.conn.execute(
                    "SELECT event_id, payload_hash FROM event_dedup WHERE dedupe_key = ?",
                    (dedupe_key,),
                ).fetchone()
                if row is not None:
                    if str(row[1]) != p_hash:
                        raise DedupeConflictError(
                            f"dedupe_key conflict for {dedupe_key}: payload changed"
                        )
                    existing = self.conn.execute(
                        "SELECT * FROM events WHERE id = ?",
                        (str(row[0]),),
                    ).fetchone()
                    if existing is None:
                        raise EventStoreError("dedup index points to missing event")
                    return self._row_to_event(existing)

            eid = event_id or str(uuid.uuid4())
            prev = self._last_hash
            h = compute_event_hash(prev_hash=prev, event_type=event_type, payload=payload_canon)

            try:
                with self.conn:
                    self.conn.execute(
                        """
                        INSERT INTO events (
                            id, type, ts, observed_at, source, trace_id, schema_version, dedupe_key,
                            payload, prev_hash, hash
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            eid,
                            str(event_type),
                            _dt_to_iso(now),
                            _dt_to_iso(observed_at),
                            source,
                            trace_id,
                            schema_version,
                            dedupe_key,
                            canonical_json(payload_canon),
                            prev,
                            h,
                        ),
                    )
                    if dedupe_key is not None:
                        self.conn.execute(
                            """
                            INSERT INTO event_dedup (dedupe_key, event_id, payload_hash, created_at)
                            VALUES (?, ?, ?, datetime('now'))
                            """,
                            (dedupe_key, eid, p_hash),
                        )
            except sqlite3.IntegrityError as e:
                raise EventStoreError(str(e)) from e

            self._last_hash = h
            return Event(
                id=eid,
                type=event_type,
                ts=now,
                observed_at=observed_at,
                source=source,
                trace_id=trace_id,
                schema_version=schema_version,
                dedupe_key=dedupe_key,
                payload=payload_canon,
                prev_hash=prev,
                hash=h,
            )

    def append_events_batch(
        self,
        events: Iterable[tuple[EventType, dict[str, Any], str | None]],
        *,
        source: str | None = None,
    ) -> list[Event]:
        """Append a batch of events atomically.

        Input tuples: (event_type, payload, dedupe_key)
        """

        out: list[Event] = []
        with self._lock:
            for et, payload, dedupe_key in events:
                out.append(
                    self.append_event(
                        event_type=et, payload=payload, dedupe_key=dedupe_key, source=source
                    )
                )
        return out

    def get_events(
        self,
        *,
        event_type: EventType | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        source: str | None = None,
        limit: int = 100,
    ) -> list[Event]:
        q = "SELECT * FROM events WHERE 1=1"
        params: list[Any] = []
        if event_type is not None:
            q += " AND type = ?"
            params.append(str(event_type))
        if source is not None:
            q += " AND source = ?"
            params.append(source)
        if since is not None:
            q += " AND ts >= ?"
            params.append(_dt_to_iso(since))
        if until is not None:
            q += " AND ts <= ?"
            params.append(_dt_to_iso(until))
        q += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(q, tuple(params)).fetchall()
        return [self._row_to_event(r) for r in rows]

    def verify_hash_chain(self, *, fast: bool = False, last_n: int = 2000) -> bool:
        """Verify the event hash chain.

        fast=True verifies only the last N events.
        """

        q = (
            "SELECT id, type, payload, prev_hash, hash FROM events "
            "ORDER BY created_at ASC, rowid ASC"
        )
        rows = self.conn.execute(q).fetchall()
        if fast and len(rows) > last_n:
            rows = rows[-last_n:]
            # For partial verification we trust the first row's prev_hash.
            prev = str(rows[0][3]) if rows[0][3] is not None else None
        else:
            prev = None

        for row in rows:
            et = EventType(str(row[1]))
            payload = json.loads(str(row[2]))
            expected = compute_event_hash(prev_hash=prev, event_type=et, payload=payload)
            if expected != str(row[4]):
                return False
            prev = expected
        return True

    def _row_to_event(self, row: sqlite3.Row) -> Event:
        payload = json.loads(row["payload"])
        return Event(
            id=str(row["id"]),
            type=EventType(str(row["type"])),
            ts=_iso_to_dt(str(row["ts"])) or datetime.now(tz=UTC),
            observed_at=_iso_to_dt(row["observed_at"]) if row["observed_at"] else None,
            source=row["source"],
            trace_id=row["trace_id"],
            schema_version=str(row["schema_version"]),
            dedupe_key=row["dedupe_key"],
            payload=payload,
            prev_hash=row["prev_hash"],
            hash=str(row["hash"]),
        )
